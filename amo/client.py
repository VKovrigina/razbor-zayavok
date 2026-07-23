from __future__ import annotations

import requests

from amo.auth import get_access_token
from config import settings


class AmoClient:
    def __init__(self) -> None:
        self.base_url = settings.amocrm_base_url.rstrip("/")

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {get_access_token()}",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        url = f"{self.base_url}{path}"
        resp = requests.request(method, url, headers=self._headers(), timeout=30, **kwargs)
        resp.raise_for_status()
        return resp

    def get(self, path: str, params: dict | None = None) -> dict:
        resp = self._request("GET", path, params=params)
        return resp.json() if resp.content else {}

    def patch(self, path: str, json: dict) -> dict:
        resp = self._request("PATCH", path, json=json)
        return resp.json() if resp.content else {}

    def post(self, path: str, json: dict | list) -> dict:
        resp = self._request("POST", path, json=json)
        return resp.json() if resp.content else {}

    # --- amoCRM-специфичные вызовы -----------------------------------------

    def get_leads_in_stage(self, pipeline_id: int, status_id: int) -> list[dict]:
        """Отдаёт ВСЕ сделки на этапе, постранично (amoCRM отдаёт максимум 250 за раз).
        Безопасный лимит страниц — просто защита от бесконечного цикла при сбое API,
        не основной критерий остановки (останавливаемся, когда страница приходит пустой)."""
        limit = 250
        max_pages = 40  # безопасный потолок: 40 * 250 = 10000 сделок на этапе
        leads: list[dict] = []
        page = 1
        while page <= max_pages:
            params = {
                "filter[pipeline_id]": pipeline_id,
                "filter[statuses][0][pipeline_id]": pipeline_id,
                "filter[statuses][0][status_id]": status_id,
                "with": "contacts",
                "limit": limit,
                "page": page,
            }
            data = self.get("/api/v4/leads", params=params)
            batch = data.get("_embedded", {}).get("leads", [])
            if not batch:
                break
            leads.extend(batch)
            if len(batch) < limit:
                break
            page += 1
        return leads

    def get_contact(self, contact_id: int) -> dict:
        return self.get(f"/api/v4/contacts/{contact_id}")

    def get_lead(self, lead_id: int) -> dict:
        return self.get(f"/api/v4/leads/{lead_id}")

    def update_lead_status(self, lead_id: int, status_id: int) -> None:
        self.patch(f"/api/v4/leads/{lead_id}", {"status_id": status_id})

    def create_task(
        self, lead_id: int, responsible_user_id: int, text: str, complete_till_ts: int
    ) -> dict:
        payload = [
            {
                "text": text,
                "entity_id": lead_id,
                "entity_type": "leads",
                "responsible_user_id": responsible_user_id,
                "complete_till": complete_till_ts,
            }
        ]
        return self.post("/api/v4/tasks", payload)

    def create_note(self, lead_id: int, text: str) -> dict:
        payload = [
            {
                "entity_id": lead_id,
                "note_type": "common",
                "params": {"text": text},
            }
        ]
        return self.post("/api/v4/leads/notes", payload)


amo_client = AmoClient()
