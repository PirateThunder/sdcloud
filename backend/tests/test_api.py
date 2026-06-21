"""API endpoint tests."""

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient


class TestHealthEndpoints:
    """Tests for health check endpoints."""

    def test_health_check(self, client: TestClient) -> None:
        """Test health check endpoint returns 200."""
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "checks" in data

    def test_liveness_probe(self, client: TestClient) -> None:
        """Test liveness probe returns alive."""
        response = client.get("/api/v1/live")
        assert response.status_code == 200
        assert response.json()["alive"] is True

    def test_readiness_probe(self, client: TestClient) -> None:
        """Test readiness probe."""
        response = client.get("/api/v1/ready")
        assert response.status_code == 200
        assert "ready" in response.json()


class TestAuthEndpoints:
    """Tests for authentication endpoints."""

    def test_register_user(self, client: TestClient) -> None:
        """Test user registration."""
        response = client.post(
            "/api/v1/auth/register",
            json={
                "email": "newuser@example.com",
                "username": "newuser",
                "password": "securepassword123",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["email"] == "newuser@example.com"
        assert data["username"] == "newuser"
        assert "id" in data
        assert "hashed_password" not in data

    def test_register_duplicate_email(self, client: TestClient) -> None:
        """Test registration with duplicate email fails."""
        # First registration
        client.post(
            "/api/v1/auth/register",
            json={
                "email": "dup@example.com",
                "username": "dupuser1",
                "password": "password123",
            },
        )
        # Duplicate email
        response = client.post(
            "/api/v1/auth/register",
            json={
                "email": "dup@example.com",
                "username": "dupuser2",
                "password": "password123",
            },
        )
        assert response.status_code == 409

    def test_login_success(self, client: TestClient) -> None:
        """Test successful login returns tokens."""
        # Register first
        client.post(
            "/api/v1/auth/register",
            json={
                "email": "login@example.com",
                "username": "loginuser",
                "password": "password123",
            },
        )
        # Login
        response = client.post(
            "/api/v1/auth/login",
            json={
                "username": "loginuser",
                "password": "password123",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    def test_login_invalid_credentials(self, client: TestClient) -> None:
        """Test login with invalid credentials fails."""
        response = client.post(
            "/api/v1/auth/login",
            json={
                "username": "nonexistent",
                "password": "wrongpassword",
            },
        )
        assert response.status_code == 401

    def test_get_me_unauthenticated(self, client: TestClient) -> None:
        """Test accessing /me without auth fails."""
        response = client.get("/api/v1/auth/me")
        assert response.status_code == 401

    def test_get_me_authenticated(self, client: TestClient) -> None:
        """Test accessing /me with valid token succeeds."""
        # Register
        client.post(
            "/api/v1/auth/register",
            json={
                "email": "me@example.com",
                "username": "meuser",
                "password": "password123",
            },
        )
        # Login
        login_response = client.post(
            "/api/v1/auth/login",
            json={
                "username": "meuser",
                "password": "password123",
            },
        )
        token = login_response.json()["access_token"]

        # Get me
        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "me@example.com"
        assert data["username"] == "meuser"


class TestConversationEndpoints:
    """Tests for conversation endpoints."""

    def _get_auth_token(self, client: TestClient) -> str:
        """Helper to get an auth token."""
        client.post(
            "/api/v1/auth/register",
            json={
                "email": "conv@example.com",
                "username": "convuser",
                "password": "password123",
            },
        )
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "convuser", "password": "password123"},
        )
        return response.json()["access_token"]

    def test_create_conversation(self, client: TestClient) -> None:
        """Test creating a conversation."""
        token = self._get_auth_token(client)
        response = client.post(
            "/api/v1/conversations",
            json={"title": "Test Conversation", "model_type": "system_dynamics"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "Test Conversation"
        assert "id" in data

    def test_list_conversations(self, client: TestClient) -> None:
        """Test listing conversations."""
        token = self._get_auth_token(client)
        # Create a conversation first
        client.post(
            "/api/v1/conversations",
            json={"title": "My Conversation"},
            headers={"Authorization": f"Bearer {token}"},
        )
        # List
        response = client.get(
            "/api/v1/conversations",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_get_conversation(self, client: TestClient) -> None:
        """Test getting a specific conversation."""
        token = self._get_auth_token(client)
        create_response = client.post(
            "/api/v1/conversations",
            json={"title": "Get Me"},
            headers={"Authorization": f"Bearer {token}"},
        )
        conv_id = create_response.json()["id"]

        response = client.get(
            f"/api/v1/conversations/{conv_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Get Me"

    def test_delete_conversation(self, client: TestClient) -> None:
        """Test deleting a conversation."""
        token = self._get_auth_token(client)
        create_response = client.post(
            "/api/v1/conversations",
            json={"title": "Delete Me"},
            headers={"Authorization": f"Bearer {token}"},
        )
        conv_id = create_response.json()["id"]

        response = client.delete(
            f"/api/v1/conversations/{conv_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 204

        # Verify it's gone
        get_response = client.get(
            f"/api/v1/conversations/{conv_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert get_response.status_code == 404

    def test_unauthorized_access(self, client: TestClient) -> None:
        """Test accessing conversations without auth fails."""
        response = client.get("/api/v1/conversations")
        assert response.status_code == 401


class TestModelEndpoints:
    """Tests for generated model endpoints."""

    def _get_auth_token(self, client: TestClient) -> str:
        """Helper to get an auth token."""
        client.post(
            "/api/v1/auth/register",
            json={
                "email": "model@example.com",
                "username": "modeluser",
                "password": "password123",
            },
        )
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "modeluser", "password": "password123"},
        )
        return response.json()["access_token"]

    def test_list_models_empty(self, client: TestClient) -> None:
        """Test listing models when none exist."""
        token = self._get_auth_token(client)
        response = client.get(
            "/api/v1/models",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_get_nonexistent_model(self, client: TestClient) -> None:
        """Test getting a model that doesn't exist."""
        token = self._get_auth_token(client)
        response = client.get(
            "/api/v1/models/12345678-1234-1234-1234-123456789abc",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404


class TestRootEndpoint:
    """Tests for root endpoint."""

    def test_root(self, client: TestClient) -> None:
        """Test root endpoint."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "name" in data
        assert "version" in data
        assert data["name"] == "sdCloud"
