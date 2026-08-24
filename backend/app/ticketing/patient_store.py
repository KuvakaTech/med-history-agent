"""TicketPatient store.

Phone number is the GLOBAL unique identifier — one patient record across all hospitals.
The same person visiting two hospitals shares the same TicketPatient document.
hospital_id is NOT part of the unique key here; it only lives on TicketSession.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Optional

from app.ticketing.models import TicketPatient

log = logging.getLogger(__name__)

_mem: dict[str, dict] = {}       # patient_id → doc
_phone_index: dict[str, str] = {} # phone → patient_id  (in-memory fallback index)
_mongo_write_failed = False


def _col():
    from app.core.database import get_db
    return get_db()["ticket_patients"]


class TicketPatientStore:
    async def upsert(
        self,
        phone: str,
        name: Optional[str] = None,
        age: Optional[int] = None,
        gender: Optional[str] = None,
    ) -> TicketPatient:
        """Insert or update a patient by phone (globally unique).

        Fields name/age/gender are only written when non-None — never erased
        by a new session that didn't collect them yet.
        """
        global _mongo_write_failed

        update_fields: dict = {"updated_at": datetime.utcnow()}
        if name is not None:
            update_fields["name"] = name
        if age is not None:
            update_fields["age"] = age
        if gender is not None:
            update_fields["gender"] = gender

        new_id = str(uuid.uuid4())

        try:
            result = await _col().find_one_and_update(
                {"phone": phone},
                {
                    "$set": update_fields,
                    "$setOnInsert": {
                        "patient_id": new_id,
                        "phone": phone,
                        "created_at": datetime.utcnow(),
                    },
                },
                upsert=True,
                return_document=True,
                projection={"_id": 0},
            )
            if result:
                patient = TicketPatient.model_validate(result)
                _mem[patient.patient_id] = result
                _phone_index[phone] = patient.patient_id
                return patient
        except Exception as exc:
            log.warning("TicketPatient upsert failed, using memory: %s", exc)
            _mongo_write_failed = True

        # In-memory fallback — look up by phone
        existing_id = _phone_index.get(phone)
        if existing_id and existing_id in _mem:
            doc = _mem[existing_id]
            doc.update({k: v for k, v in update_fields.items()})
            return TicketPatient.model_validate(doc)

        # Brand new patient (memory-only)
        patient = TicketPatient(phone=phone, name=name, age=age, gender=gender)
        doc = patient.model_dump(mode="json")
        _mem[patient.patient_id] = doc
        _phone_index[phone] = patient.patient_id
        return patient

    async def get(self, patient_id: str) -> Optional[TicketPatient]:
        try:
            doc = await _col().find_one({"patient_id": patient_id}, {"_id": 0})
            if doc:
                return TicketPatient.model_validate(doc)
        except Exception as exc:
            log.warning("TicketPatient get failed: %s", exc)
        doc = _mem.get(patient_id)
        return TicketPatient.model_validate(doc) if doc else None

    async def get_by_phone(self, phone: str) -> Optional[TicketPatient]:
        try:
            doc = await _col().find_one({"phone": phone}, {"_id": 0})
            if doc:
                return TicketPatient.model_validate(doc)
        except Exception as exc:
            log.warning("TicketPatient get_by_phone failed: %s", exc)
        pid = _phone_index.get(phone)
        if pid and pid in _mem:
            return TicketPatient.model_validate(_mem[pid])
        return None

    async def update(self, patient: TicketPatient) -> TicketPatient:
        global _mongo_write_failed
        patient.updated_at = datetime.utcnow()
        doc = patient.model_dump(mode="json")
        _mem[patient.patient_id] = doc
        _phone_index[patient.phone] = patient.patient_id
        if not _mongo_write_failed:
            try:
                await _col().update_one(
                    {"patient_id": patient.patient_id},
                    {"$set": doc},
                    upsert=True,
                )
            except Exception as exc:
                log.warning("TicketPatient update failed: %s", exc)
                _mongo_write_failed = True
        return patient


ticket_patient_store = TicketPatientStore()
