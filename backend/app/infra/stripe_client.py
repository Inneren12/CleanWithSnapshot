from __future__ import annotations

import inspect
from typing import Any, Callable

import anyio

from app.infra.stripe_resilience import stripe_circuit
from app.settings import settings


MUTATING_METHOD_PREFIXES: tuple[str, ...] = (
    "create_",
    "cancel_",
    "expire_",
    "refund_",
    "update_",
    "void_",
)

READ_ONLY_METHOD_PREFIXES: tuple[str, ...] = (
    "retrieve_",
    "list_",
    "verify_",
)


def is_mutating_method(method_name: str) -> bool:
    if method_name.startswith(READ_ONLY_METHOD_PREFIXES):
        return False
    return method_name.startswith(MUTATING_METHOD_PREFIXES)


class StripeClient:
    def __init__(
        self,
        *,
        secret_key: str | None,
        webhook_secret: str | None,
        stripe_sdk: Any | None = None,
    ) -> None:
        """Initialize Stripe client credentials.

        ``settings`` is the canonical configuration source for this deployment.
        Passing ``None`` for a credential means "fall back to global settings".
        Runtime operations still fail fast with ``ValueError`` when a key is not
        configured.
        """
        if stripe_sdk is None:
            import stripe as stripe_sdk  # type: ignore

        self.stripe = stripe_sdk
        self.secret_key = secret_key or settings.stripe_secret_key
        self.webhook_secret = webhook_secret or settings.stripe_webhook_secret

    def _stripe_request_timeout(self) -> float:
        timeout = stripe_circuit.timeout_seconds
        if timeout is None:
            return 10.0
        return max(0.01, timeout)

    async def _call(self, fn: Callable[..., Any], /, *args, **kwargs) -> Any:
        request_kwargs = dict(kwargs)
        try:
            signature = inspect.signature(fn)
            supports_timeout = any(
                parameter.kind == inspect.Parameter.VAR_KEYWORD or name == "timeout"
                for name, parameter in signature.parameters.items()
            )
        except (TypeError, ValueError):
            supports_timeout = True
        if supports_timeout:
            request_kwargs.setdefault("timeout", self._stripe_request_timeout())

        def _sync_call() -> Any:
            return fn(*args, **request_kwargs)

        return await stripe_circuit.call(lambda: anyio.to_thread.run_sync(_sync_call))

    async def create_checkout_session(
        self,
        *,
        amount_cents: int,
        currency: str,
        success_url: str,
        cancel_url: str,
        metadata: dict[str, str] | None = None,
        product_name: str = "Cleaning deposit",
        payment_intent_metadata: dict[str, str] | None = None,
        customer_email: str | None = None,
        idempotency_key: str | None = None,
    ) -> Any:
        if not self.secret_key:
            raise ValueError("Stripe secret key not configured")

        self.stripe.api_key = self.secret_key
        payload = {
            "mode": "payment",
            "payment_method_types": ["card"],
            "success_url": success_url,
            "cancel_url": cancel_url,
            "line_items": [
                {
                    "price_data": {
                        "currency": currency,
                        "product_data": {"name": product_name},
                        "unit_amount": amount_cents,
                    },
                    "quantity": 1,
                }
            ],
            "metadata": metadata or {},
        }
        if payment_intent_metadata:
            payload["payment_intent_data"] = {"metadata": payment_intent_metadata}
        if customer_email:
            payload["customer_email"] = customer_email
        extra: dict[str, Any] = {}
        if idempotency_key:
            extra["idempotency_key"] = idempotency_key
        return await self._call(self.stripe.checkout.Session.create, **payload, **extra)

    async def create_subscription_checkout_session(
        self,
        *,
        price_cents: int,
        currency: str,
        success_url: str,
        cancel_url: str,
        metadata: dict[str, str] | None = None,
        customer: str | None = None,
        price_id: str | None = None,
        plan_name: str = "SaaS Subscription",
        idempotency_key: str | None = None,
    ) -> Any:
        if not self.secret_key:
            raise ValueError("Stripe secret key not configured")

        self.stripe.api_key = self.secret_key
        price_configuration: dict[str, Any]
        if price_id:
            price_configuration = {"price": price_id}
        else:
            price_configuration = {
                "price_data": {
                    "currency": currency,
                    "product_data": {"name": plan_name},
                    "unit_amount": price_cents,
                    "recurring": {"interval": "month"},
                }
            }

        payload: dict[str, Any] = {
            "mode": "subscription",
            "success_url": success_url,
            "cancel_url": cancel_url,
            "line_items": [price_configuration],
            "metadata": metadata or {},
        }
        if customer:
            payload["customer"] = customer
        extra: dict[str, Any] = {}
        if idempotency_key:
            extra["idempotency_key"] = idempotency_key
        return await self._call(self.stripe.checkout.Session.create, **payload, **extra)

    async def cancel_checkout_session(self, session_id: str, *, idempotency_key: str | None = None) -> Any:
        """Best-effort expire (cancel) of a Stripe Checkout Session.

        Stripe uses ``Session.expire`` to prevent further payment collection on
        an open checkout session.
        """
        if not self.secret_key:
            raise ValueError("Stripe secret key not configured")
        self.stripe.api_key = self.secret_key
        extra: dict[str, Any] = {}
        if idempotency_key:
            extra["idempotency_key"] = idempotency_key
        return await self._call(self.stripe.checkout.Session.expire, session_id, **extra)

    async def retrieve_checkout_session(self, session_id: str) -> Any:
        """Retrieve an existing Stripe Checkout Session by ID."""
        if not self.secret_key:
            raise ValueError("Stripe secret key not configured")
        self.stripe.api_key = self.secret_key
        return await self._call(self.stripe.checkout.Session.retrieve, session_id)

    async def create_billing_portal_session(
        self,
        *,
        customer_id: str,
        return_url: str,
        idempotency_key: str | None = None,
    ) -> Any:
        if not self.secret_key:
            raise ValueError("Stripe secret key not configured")

        self.stripe.api_key = self.secret_key
        extra: dict[str, Any] = {}
        if idempotency_key:
            extra["idempotency_key"] = idempotency_key
        return await self._call(
            self.stripe.billing_portal.Session.create,
            customer=customer_id,
            return_url=return_url,
            **extra,
        )

    async def verify_webhook(self, payload: bytes, signature: str | None) -> Any:
        if not self.webhook_secret:
            raise ValueError("Stripe webhook secret not configured")
        if not signature:
            raise ValueError("Missing Stripe signature header")
        return await self._call(
            self.stripe.Webhook.construct_event,
            payload=payload,
            sig_header=signature,
            secret=self.webhook_secret,
        )


def resolve_client(app_state: Any) -> StripeClient:
    """Resolve StripeClient for current app state.

    Priority:
    1) services.stripe_client
    2) state.stripe_client
    3) Create new StripeClient with resolved keys

    Resolution order for credentials:
    app_settings -> global settings

    Existing non-empty credentials are never overwritten.
    """
    state = getattr(app_state, "state", app_state)
    services = getattr(state, "services", None)
    if services is not None:
        client = getattr(services, "stripe_client", None)
        if client is not None:
            return client
    client = getattr(state, "stripe_client", None)
    app_settings = getattr(state, "app_settings", None)
    resolved_secret_key = (
        getattr(app_settings, "stripe_secret_key", None)
        or settings.stripe_secret_key
    )
    resolved_webhook_secret = (
        getattr(app_settings, "stripe_webhook_secret", None)
        or settings.stripe_webhook_secret
    )

    # Stripe keys are global for this deployment (not per-tenant). If that
    # assumption changes, this hydration logic must be revisited.
    if isinstance(client, StripeClient):
        if not client.secret_key:
            client.secret_key = resolved_secret_key
        if not client.webhook_secret:
            client.webhook_secret = resolved_webhook_secret
    if client is None:
        client = StripeClient(
            secret_key=resolved_secret_key,
            webhook_secret=resolved_webhook_secret,
        )
        state.stripe_client = client
    return client


async def call_stripe_client_method(client: Any, method_name: str, /, *args, **kwargs) -> Any:
    method = getattr(client, method_name)
    if method is None:
        raise AttributeError(f"Stripe client missing method {method_name}")

    if is_mutating_method(method_name) and not kwargs.get("idempotency_key"):
        raise ValueError(
            f"Stripe mutation '{method_name}' requires idempotency_key to be provided"
        )

    result = method(*args, **kwargs)
    if inspect.isawaitable(result):
        return await result
    return result
