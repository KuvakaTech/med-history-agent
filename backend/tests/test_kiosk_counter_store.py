"""Tests for kiosk complaint number counter."""
from __future__ import annotations

import os
import re

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-pytest-only")

import pytest
from unittest.mock import patch

from app.kiosk.counter_store import next_complaint_number


@pytest.mark.asyncio
async def test_complaint_number_format():
    centre_id = "test-centre-uuid"
    with patch("app.kiosk.counter_store._col", side_effect=RuntimeError("no mongo")):
        num = await next_complaint_number(centre_id)
    assert re.match(r"^JS-VNS-\d{8}-\d{5}$", num)


@pytest.mark.asyncio
async def test_complaint_number_custom_prefix():
    centre_id = "nagar-centre"
    with patch("app.kiosk.counter_store._col", side_effect=RuntimeError("no mongo")):
        num = await next_complaint_number(centre_id, prefix="NN-VNS")
    assert re.match(r"^NN-VNS-\d{8}-\d{5}$", num)
