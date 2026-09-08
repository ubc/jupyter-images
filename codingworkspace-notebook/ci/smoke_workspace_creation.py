"""Exercise the browser creation protocol through an authenticated image proxy."""
from __future__ import annotations

import argparse
import json
import os
import time
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener


class SmokeError(RuntimeError):
    pass


def wait_creation(request, receipt, *, timeout=120, clock=time.monotonic, pause=time.sleep):
    request_id = receipt.get("id")
    if not isinstance(request_id, str) or not request_id:
        raise SmokeError("Missing creation receipt identity")
    deadline = clock() + timeout
    while clock() < deadline:
        status, payload = request("GET", "/api/workspace-creations/" + request_id)
        operation = payload.get("creation", {})
        if status != 200 or operation.get("id") != request_id:
            raise SmokeError("Creation poll returned a different or unavailable receipt")
        if operation.get("status") == "completed":
            workspace_id = operation.get("workspaceId")
            if not workspace_id or payload.get("workspace", {}).get("id") != workspace_id:
                raise SmokeError("Completed creation does not identify its actual workspace")
            return workspace_id
        if operation.get("status") not in {"queued", "creating"}:
            raise SmokeError("Creation failed or returned an unknown state")
        pause(0.25)
    raise SmokeError("Creation did not complete before the smoke deadline")


def verify_workspace(request, workspace_id, request_id=None):
    status, payload = request("GET", "/api/workspaces")
    matches = [item for item in payload.get("workspaces", []) if item.get("id") == workspace_id]
    if status != 200 or len(matches) != 1:
        raise SmokeError("Retained workspace is missing or duplicated")
    if request_id:
        status, payload = request("GET", "/api/workspace-creations/" + request_id)
        receipt = payload.get("creation", {})
        if (status != 200 or receipt.get("id") != request_id
                or receipt.get("status") != "completed"
                or receipt.get("workspaceId") != workspace_id
                or payload.get("workspace", {}).get("id") != workspace_id):
            raise SmokeError("Retained creation receipt no longer identifies its workspace")


def create_workspace(request, request_id, *, legacy=False):
    status, bootstrap = request("GET", "/api/bootstrap")
    if status != 200:
        raise SmokeError("Authenticated bootstrap did not succeed")
    active = bootstrap.get("workspaceCreation")
    if active and active.get("status") in {"queued", "creating"}:
        wait_creation(request, active)
    body = {"assignmentSlug": "image-smoke", "displayName": "Image smoke starter"}
    if not legacy:
        body["creationRequestId"] = request_id
    status, payload = request("POST", "/api/workspaces", body)
    if legacy:
        workspace_id = payload.get("workspace", {}).get("id")
        if status != 201 or not workspace_id:
            raise SmokeError("Prior image legacy creation did not produce a workspace")
    else:
        if status != 202 or payload.get("creation", {}).get("id") != request_id:
            raise SmokeError("Async creation was not accepted with its stable receipt")
        # Repeat the same request as after a lost acceptance response. Both an
        # in-progress replay and an already-completed replay must be harmless.
        status, replay = request("POST", "/api/workspaces", body)
        if status != 202 or replay.get("creation", {}).get("id") != request_id:
            raise SmokeError("Acceptance replay did not reuse the creation receipt")
        workspace_id = wait_creation(request, replay["creation"])
        status, completed = request("POST", "/api/workspaces", body)
        receipt = completed.get("creation", {})
        if (status != 202 or receipt.get("status") != "completed"
                or receipt.get("workspaceId") != workspace_id):
            raise SmokeError("Completed replay did not reuse the workspace")
    verify_workspace(request, workspace_id, None if legacy else request_id)
    status, payload = request("GET", "/api/workspaces")
    matches = [item for item in payload.get("workspaces", []) if item.get("assignmentSlug") == "image-smoke"]
    if status != 200 or len(matches) != 1 or matches[0].get("id") != workspace_id:
        raise SmokeError("Creation or response replay duplicated the smoke project")
    return workspace_id


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("create", "legacy", "verify"))
    parser.add_argument("base_url")
    parser.add_argument("identity")
    parser.add_argument("--request-id")
    args = parser.parse_args()
    # The caller runs this inside a disposable Docker container. Do not accept
    # an arbitrary remote URL and accidentally forward its smoke token.
    if not args.base_url.startswith("http://127.0.0.1:8888/user/"):
        raise SmokeError("Expected the disposable local Jupyter proxy")
    opener = build_opener(NoRedirects())

    def request(method, path, body=None):
        encoded = None if body is None else json.dumps(body).encode()
        req = Request(args.base_url.rstrip("/") + path, data=encoded, method=method,
                      headers={"Authorization": "token " + os.environ["CW_SMOKE_TOKEN"],
                               "X-CodingWorkspace-Request": "1", "Content-Type": "application/json"})
        try:
            response = opener.open(req, timeout=15)
        except HTTPError as exc:
            response = exc
        with response:
            raw = response.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024:
                raise SmokeError("Image proxy response exceeded the smoke limit")
            try:
                payload = json.loads(raw)
            except (UnicodeError, ValueError):
                raise SmokeError("Image proxy did not return JSON") from None
            if not isinstance(payload, dict):
                raise SmokeError("Image proxy returned an unexpected JSON shape")
            return response.status, payload

    if args.mode == "verify":
        verify_workspace(request, args.identity, args.request_id)
    else:
        print(create_workspace(request, args.identity, legacy=args.mode == "legacy"))


if __name__ == "__main__":
    main()
