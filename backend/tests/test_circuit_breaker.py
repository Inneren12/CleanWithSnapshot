import asyncio
from concurrent.futures import ThreadPoolExecutor
import time

import anyio
import pytest

from app.shared.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError


@pytest.mark.anyio
async def test_circuit_opens_after_failures():
    breaker = CircuitBreaker(name="email", failure_threshold=2, recovery_time=0.1, window_seconds=10)

    with pytest.raises(RuntimeError):
        await breaker.call(lambda: (_ for _ in ()).throw(RuntimeError("fail")))
    with pytest.raises(RuntimeError):
        await breaker.call(lambda: (_ for _ in ()).throw(RuntimeError("fail")))

    with pytest.raises(CircuitBreakerOpenError):
        await breaker.call(lambda: "ok")

    await anyio.sleep(0.11)
    with pytest.raises(RuntimeError):
        await breaker.call(lambda: (_ for _ in ()).throw(RuntimeError("fail")))
    assert breaker.state == "open"


@pytest.mark.anyio
async def test_circuit_half_open_allows_success_and_closes():
    breaker = CircuitBreaker(name="stripe", failure_threshold=1, recovery_time=0.05)

    with pytest.raises(RuntimeError):
        await breaker.call(lambda: (_ for _ in ()).throw(RuntimeError("fail")))

    await anyio.sleep(0.12)
    result = await breaker.call(lambda: "success")

    assert result == "success"
    assert breaker.state == "closed"


@pytest.mark.anyio
async def test_circuit_timeout_marks_failure_and_opens():
    breaker = CircuitBreaker(
        name="stripe-timeout",
        failure_threshold=1,
        recovery_time=1.0,
        window_seconds=10,
        timeout_seconds=0.01,
    )

    with pytest.raises(TimeoutError):
        await breaker.call(lambda: anyio.to_thread.run_sync(lambda: time.sleep(0.05)))

    assert breaker.state == "open"
    with pytest.raises(CircuitBreakerOpenError):
        await breaker.call(lambda: "ok")


@pytest.mark.anyio
async def test_circuit_timeout_applies_to_task_returned_by_function():
    breaker = CircuitBreaker(
        name="stripe-task-timeout",
        failure_threshold=1,
        recovery_time=1.0,
        window_seconds=10,
        timeout_seconds=0.01,
    )

    task = asyncio.create_task(anyio.sleep(0.05))

    with pytest.raises(TimeoutError):
        await breaker.call(lambda: task)

    assert breaker.state == "open"


@pytest.mark.anyio
async def test_circuit_timeout_applies_to_future_returned_by_function():
    breaker = CircuitBreaker(
        name="stripe-future-timeout",
        failure_threshold=1,
        recovery_time=1.0,
        window_seconds=10,
        timeout_seconds=0.01,
    )

    loop = asyncio.get_running_loop()
    future = loop.run_in_executor(None, time.sleep, 0.05)

    with pytest.raises(TimeoutError):
        await breaker.call(lambda: future)

    assert breaker.state == "open"


@pytest.mark.anyio
async def test_circuit_timeout_override_takes_precedence_over_default_timeout():
    breaker = CircuitBreaker(
        name="stripe-timeout-override",
        failure_threshold=1,
        recovery_time=1.0,
        window_seconds=10,
        timeout_seconds=0.5,
    )

    with pytest.raises(TimeoutError):
        await breaker.call(lambda: anyio.sleep(0.05), timeout_seconds=0.01)

    assert breaker.state == "open"


@pytest.mark.anyio
async def test_circuit_timeout_applies_to_concurrent_futures_future():
    breaker = CircuitBreaker(
        name="stripe-concurrent-future-timeout",
        failure_threshold=1,
        recovery_time=1.0,
        window_seconds=10,
        timeout_seconds=0.01,
    )

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(time.sleep, 0.05)
        with pytest.raises(TimeoutError):
            await breaker.call(lambda: future)

    assert breaker.state == "open"
