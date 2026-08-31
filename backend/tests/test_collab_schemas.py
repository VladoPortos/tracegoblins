from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.api.collab_schemas import (
    TAG_VALUES,
    AnnotationCreate,
    AnnotationLink,
    AnnotationOut,
    CommentCreate,
    CommentOut,
    MentionableUser,
    NotificationListOut,
    NotificationOut,
    UnreadCountOut,
    MarkReadIn,
)
from app.security.urls import _ALLOWED_SCHEMES
from app.services.collab_query import annotation_to_out, comment_to_out


def test_tag_values_and_schemes_are_exact():
    assert TAG_VALUES == frozenset({"needs-fix", "known-issue", "resolved", "note"})
    # pin the enforced link-URL scheme allowlist (app.security.urls is what write paths use)
    assert _ALLOWED_SCHEMES == frozenset({"http", "https", "mailto"})


def test_annotation_create_defaults_are_empty():
    a = AnnotationCreate()
    assert a.note == "" and a.tags == [] and a.links == []


def test_comment_create_requires_body_only():
    c = CommentCreate(body="hi")
    assert c.body == "hi" and c.mentions == [] and c.parent_id is None and c.annotation_id is None
    with pytest.raises(Exception):
        CommentCreate()  # body is required


class _FakeAnnotation:
    def __init__(self):
        self.id = uuid.uuid4()
        self.run_id = uuid.uuid4()
        self.task_seq = 7
        self.author_user_id = uuid.uuid4()
        self.note = "look here"
        self.tags = ["needs-fix"]
        self.links = [{"label": "ticket", "url": "https://x/1"}]
        self.resolved = False
        self.created_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)


def test_annotation_to_out_maps_links_and_author_name():
    a = _FakeAnnotation()
    out = annotation_to_out(a, author_name="Ada")
    assert isinstance(out, AnnotationOut)
    assert out.id == str(a.id) and out.run_id == str(a.run_id)
    assert out.task_seq == 7 and out.author_user_id == str(a.author_user_id)
    assert out.author_name == "Ada" and out.note == "look here"
    assert out.tags == ["needs-fix"]
    assert out.links == [AnnotationLink(label="ticket", url="https://x/1")]
    assert out.resolved is False


class _FakeComment:
    def __init__(self, deleted: bool):
        self.id = uuid.uuid4()
        self.run_id = uuid.uuid4()
        self.task_seq = 3
        self.annotation_id = None
        self.parent_id = None
        self.author_user_id = uuid.uuid4()
        self.body = "hello @Bo" if not deleted else "hello @Bo"
        self.mentions = [uuid.uuid4()]
        self.created_at = datetime.now(timezone.utc)
        self.edited_at = None
        self.deleted_at = datetime.now(timezone.utc) if deleted else None


def test_comment_to_out_live_carries_body():
    c = _FakeComment(deleted=False)
    out = comment_to_out(c, author_name="Bo")
    assert isinstance(out, CommentOut)
    assert out.body == "hello @Bo" and out.author_name == "Bo"
    assert out.mentions == [str(c.mentions[0])]
    assert out.deleted_at is None


def test_comment_to_out_tombstone_nulls_body():
    c = _FakeComment(deleted=True)
    out = comment_to_out(c, author_name="Bo")
    assert out.body is None  # tombstone hides text
    assert out.deleted_at is not None


def test_mentionable_user_optional_fields():
    m = MentionableUser(id="1", display_name="Ada", email="ada@example.com")
    assert m.initials is None and m.avatar_color is None


def test_notification_out_schema():
    now = datetime.now(timezone.utc)
    n = NotificationOut(
        id="abc",
        type="mention",
        run_id=None,
        run_template=None,
        task_seq=None,
        task_name=None,
        actor_user_id=None,
        actor_name=None,
        read_at=None,
        created_at=now,
    )
    assert n.type == "mention" and n.read_at is None and n.run_id is None


def test_notification_list_out_schema():
    now = datetime.now(timezone.utc)
    n = NotificationOut(
        id="x", type="share", run_id="r1", run_template="My Template",
        task_seq=3, task_name="Install package",
        actor_user_id="u1", actor_name="Alice",
        read_at=None, created_at=now,
    )
    lst = NotificationListOut(items=[n])
    assert len(lst.items) == 1


def test_unread_count_out_schema():
    u = UnreadCountOut(count=5)
    assert u.count == 5


def test_mark_read_in_schema():
    m = MarkReadIn(ids=["a", "b"])
    assert m.all is False and m.ids == ["a", "b"]

    m2 = MarkReadIn(all=True)
    assert m2.all is True and m2.ids is None
