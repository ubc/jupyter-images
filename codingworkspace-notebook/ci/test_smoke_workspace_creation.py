"""Regression checks for asynchronous creation and retained-home smoke evidence."""
import unittest

from smoke_workspace_creation import SmokeError, create_workspace, verify_workspace, wait_creation


class CreationServer:
    def __init__(self):
        self.posts = []
        self.workspace_id = "ws-0123456789ab"
        self.complete = False
        self.duplicate = False
        self.failed = False
        self.wrong_receipt = False
        self.legacy = False
        self.old_receipt = False

    def request(self, method, path, body=None):
        if path == "/api/bootstrap":
            return 200, {"workspaceCreation": None}
        if path == "/api/workspaces" and method == "POST":
            self.posts.append(dict(body))
            if self.legacy:
                self.complete = True
                return 201, {"workspace": {"id": self.workspace_id}}
            self.request_id = body["creationRequestId"]
            return 202, {"creation": self.receipt()}
        if path.startswith("/api/workspace-creations/"):
            self.complete = not self.failed
            return 200, {"creation": self.receipt(), "workspace": {"id": self.workspace_id}}
        if path == "/api/workspaces":
            workspace = {"id": self.workspace_id, "assignment_slug": "image-smoke"}
            rows = [workspace] if self.complete else []
            if self.duplicate:
                rows.append({"id": "ws-111111111111", "assignment_slug": "image-smoke"})
            return 200, {"workspaces": rows}
        raise AssertionError((method, path))

    def receipt(self):
        return {"id": "another-receipt-id" if self.wrong_receipt else self.request_id,
                "status": "failed" if self.failed else "completed" if self.complete else "creating",
                "workspaceId": "ws-000000000000" if self.old_receipt else self.workspace_id if self.complete else None}


class CreationSmokeTests(unittest.TestCase):
    def test_retries_identical_request_and_verifies_one_workspace(self):
        server = CreationServer()
        self.assertEqual(create_workspace(server.request, "image-smoke-request"), server.workspace_id)
        self.assertEqual(len(server.posts), 3)
        self.assertEqual(server.posts, [server.posts[0]] * 3)

    def test_duplicate_project_is_not_passing_evidence(self):
        server = CreationServer()
        server.duplicate = True
        with self.assertRaisesRegex(SmokeError, "duplicated"):
            create_workspace(server.request, "image-smoke-request")

    def test_old_synchronous_endpoint_does_not_pass_new_async_smoke(self):
        server = CreationServer()
        server.legacy = True
        with self.assertRaisesRegex(SmokeError, "Async creation"):
            create_workspace(server.request, "image-smoke-request")

    def test_prior_image_fixture_uses_legacy_creation_without_request_id(self):
        server = CreationServer()
        server.legacy = True
        self.assertEqual(create_workspace(server.request, "unused", legacy=True), server.workspace_id)
        self.assertNotIn("creationRequestId", server.posts[0])
        verify_workspace(server.request, server.workspace_id)

    def test_failed_or_swapped_receipt_is_not_success(self):
        for attr in ("failed", "wrong_receipt", "old_receipt"):
            with self.subTest(attr=attr):
                server = CreationServer()
                setattr(server, attr, True)
                with self.assertRaises(SmokeError):
                    create_workspace(server.request, "image-smoke-request")

    def test_retained_receipt_must_still_identify_same_workspace(self):
        server = CreationServer()
        create_workspace(server.request, "image-smoke-request")
        server.old_receipt = True
        with self.assertRaisesRegex(SmokeError, "Retained creation receipt"):
            verify_workspace(server.request, server.workspace_id, "image-smoke-request")

    def test_pending_poll_has_bounded_deadline(self):
        request = lambda *args: (200, {"creation": {"id": "image-smoke-request", "status": "creating"}})
        with self.assertRaisesRegex(SmokeError, "deadline"):
            wait_creation(request, {"id": "image-smoke-request"}, timeout=1,
                          clock=iter([0, 0, 2]).__next__, pause=lambda _: None)

    def test_bootstrap_creation_finishes_before_explicit_creation(self):
        server = CreationServer()
        original = server.request
        events = []

        def request(method, path, body=None):
            events.append(path)
            if path == "/api/bootstrap":
                return 200, {"workspaceCreation": {"id": "default-project-v1", "status": "creating"}}
            if path == "/api/workspace-creations/default-project-v1":
                return 200, {"creation": {"id": "default-project-v1", "status": "completed", "workspaceId": "default"},
                             "workspace": {"id": "default"}}
            return original(method, path, body)

        create_workspace(request, "image-smoke-request")
        self.assertEqual(events[:3], ["/api/bootstrap", "/api/workspace-creations/default-project-v1", "/api/workspaces"])


if __name__ == "__main__":
    unittest.main()
