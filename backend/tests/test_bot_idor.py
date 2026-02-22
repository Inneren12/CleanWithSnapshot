def test_post_message_enforces_user_ownership(client):
    conversation_id = client.post(
        "/api/bot/session",
        json={"channel": "web", "userId": "user-a"},
    ).json()["conversationId"]

    forbidden = client.post(
        "/api/bot/message",
        json={"conversationId": conversation_id, "text": "hello", "userId": "user-b"},
    )
    assert forbidden.status_code == 403

    allowed = client.post(
        "/api/bot/message",
        json={"conversationId": conversation_id, "text": "hello", "userId": "user-a"},
    )
    assert allowed.status_code == 200


def test_get_endpoints_enforce_anonymous_session_cookie_binding(client):
    conversation_id = client.post(
        "/api/bot/session",
        json={"channel": "web", "anonId": "anon-a"},
    ).json()["conversationId"]

    client.cookies.set("anon_session_id", "anon-b")
    forbidden_messages = client.get("/api/bot/messages", params={"conversationId": conversation_id})
    assert forbidden_messages.status_code == 403

    forbidden_session = client.get(f"/api/bot/session/{conversation_id}")
    assert forbidden_session.status_code == 403

    client.cookies.set("anon_session_id", "anon-a")
    allowed_messages = client.get("/api/bot/messages", params={"conversationId": conversation_id})
    assert allowed_messages.status_code == 200

    allowed_session = client.get(f"/api/bot/session/{conversation_id}")
    assert allowed_session.status_code == 200
