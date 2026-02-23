import anyio

from app.domain.bot.schemas import ConversationCreate, ConversationState
from app.main import app


def test_post_message_enforces_user_ownership(client):
    create_response = client.post(
        "/api/bot/session",
        json={"channel": "web", "userId": "victim-in-body"},
        headers={"X-Test-User-Id": "user-a"},
    )
    assert create_response.status_code == 201
    conversation_id = create_response.json()["conversationId"]

    forbidden = client.post(
        "/api/bot/message",
        json={"conversationId": conversation_id, "text": "hello", "userId": "user-a"},
        headers={"X-Test-User-Id": "user-b"},
    )
    assert forbidden.status_code == 403

    allowed = client.post(
        "/api/bot/message",
        json={"conversationId": conversation_id, "text": "hello", "userId": "user-a"},
        headers={"X-Test-User-Id": "user-a"},
    )
    assert allowed.status_code == 200


def test_get_endpoints_enforce_anonymous_session_cookie_binding(client):
    create_response = client.post(
        "/api/bot/session",
        json={"channel": "web", "anonId": "attacker-body-anon"},
    )
    assert create_response.status_code == 201
    conversation_id = create_response.json()["conversationId"]
    anon_cookie = create_response.cookies.get("anon_session_id")
    assert anon_cookie

    client.cookies.set("anon_session_id", "anon-b")
    forbidden_messages = client.get("/api/bot/messages", params={"conversationId": conversation_id})
    assert forbidden_messages.status_code == 403

    forbidden_session = client.get(f"/api/bot/session/{conversation_id}")
    assert forbidden_session.status_code == 403

    client.cookies.set("anon_session_id", anon_cookie)
    allowed_messages = client.get("/api/bot/messages", params={"conversationId": conversation_id})
    assert allowed_messages.status_code == 200

    allowed_session = client.get(f"/api/bot/session/{conversation_id}")
    assert allowed_session.status_code == 200


def test_conversation_without_binding_is_denied_by_default(client):
    conversation = anyio.run(
        app.state.bot_store.create_conversation,
        ConversationCreate(channel="web", state=ConversationState()),
    )

    messages_response = client.get(
        "/api/bot/messages",
        params={"conversationId": conversation.conversation_id},
    )
    assert messages_response.status_code == 403

    session_response = client.get(f"/api/bot/session/{conversation.conversation_id}")
    assert session_response.status_code == 403

    post_response = client.post(
        "/api/bot/message",
        json={"conversationId": conversation.conversation_id, "text": "hello"},
    )
    assert post_response.status_code == 403
