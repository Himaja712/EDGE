from locust import HttpUser, task, between
import random
import uuid

USERS = [
    {"username": "hpendyala@nicesoftwaresolutions.com", "password": "anything", "role": "reportee", "weight": 50},
    {"username": "sonal@nss.com", "password": "anything", "role": "manager", "weight": 30},
    {"username": "shailesh@nss.com", "password": "anything", "role": "approver", "weight": 15},
    {"username": "Admin", "password": "Admin@123", "role": "admin", "weight": 5},
]

def weighted_user():
    pool = []
    for user in USERS:
        pool.extend([user] * user["weight"])
    return random.choice(pool)

class PMSWriteUser(HttpUser):
    fixed_count = 100
    wait_time = between(2, 6)

    def on_start(self):
        self.headers = {}
        self.role = None
        self.user = weighted_user()
        self.role = self.user["role"]

        res = self.client.post("/api/auth/login", json={
            "username": self.user["username"],
            "password": self.user["password"],
        })

        if res.status_code == 200:
            token = res.json()["access_token"]
            self.headers = {"Authorization": f"Bearer {token}"}

    def get_json(self, path, params=None, name=None):
        if not self.headers:
            return None
        res = self.client.get(path, headers=self.headers, params=params, name=name or path)
        if res.status_code == 200:
            data = res.json()
            return data.get("items", data) if isinstance(data, dict) else data
        return None

    def post_json(self, path, payload=None, name=None):
        if not self.headers:
            return
        with self.client.post(
            path,
            json=payload or {},
            headers=self.headers,
            name=name or path,
            catch_response=True,
        ) as res:
            if res.status_code in [200, 201]:
                res.success()
            elif res.status_code in [400, 403, 404]:
                # Business-state conflicts are expected in write load tests:
                # already submitted, not open, not authorized, no diary found, etc.
                res.success()
            else:
                res.failure(f"{res.status_code}: {res.text[:300]}")

    def put_json(self, path, payload=None, name=None):
        if not self.headers:
            return
        with self.client.put(
            path,
            json=payload or {},
            headers=self.headers,
            name=name or path,
            catch_response=True,
        ) as res:
            if res.status_code in [200, 201, 400, 403, 404]:
                res.success()
            else:
                res.failure(f"{res.status_code}: {res.text[:300]}")

    def delete_req(self, path, name=None):
        if not self.headers:
            return
        with self.client.delete(
            path,
            headers=self.headers,
            name=name or path,
            catch_response=True,
        ) as res:
            if res.status_code in [200, 400, 403, 404]:
                res.success()
            else:
                res.failure(f"{res.status_code}: {res.text[:300]}")

    @task(4)
    def manager_allocate_and_submit_kras(self):
        if self.role != "manager":
            return

        diaries = self.get_json("/api/diaries/team", {"page": 1, "page_size": 25}) or []
        candidates = [
            d for d in diaries
            if d.get("kra_status") in ["draft", "sent_back"]
            and d.get("employee")
            and d["employee"].get("band_id")
        ]

        if not candidates:
            return

        diary = random.choice(candidates)
        diary_id = diary["id"]
        band_id = diary["employee"]["band_id"]

        kra_master = self.get_json("/api/kra-master", {"band_id": band_id}, name="/api/kra-master?band_id={band_id}") or []
        usable_kras = [k for k in kra_master if k.get("kpis")]

        if len(usable_kras) < 2:
            return

        selected = usable_kras[:2]
        payload = {
            "kras": [
                {
                    "kra_master_id": selected[0]["id"],
                    "weightage_pct": 50,
                    "kpi_ids": [selected[0]["kpis"][0]["id"]],
                    "custom_kpis": [],
                    "measurement_comment": "Load test measurement comment",
                },
                {
                    "kra_master_id": selected[1]["id"],
                    "weightage_pct": 50,
                    "kpi_ids": [selected[1]["kpis"][0]["id"]],
                    "custom_kpis": [],
                    "measurement_comment": "Load test measurement comment",
                },
            ]
        }

        self.post_json(
            f"/api/diaries/{diary_id}/allocate-kras",
            payload,
            name="/api/diaries/{diary_id}/allocate-kras",
        )
        self.post_json(
            f"/api/diaries/{diary_id}/submit-kras",
            name="/api/diaries/{diary_id}/submit-kras",
        )

    @task(4)
    def reportee_self_rating(self):
        if self.role != "reportee":
            return

        diaries = self.get_json("/api/diaries/my", {"page": 1, "page_size": 25}) or []
        candidates = [d for d in diaries if d.get("self_status") == "open"]

        if not candidates:
            return

        diary_id = random.choice(candidates)["id"]
        detail = self.get_json(f"/api/diaries/{diary_id}")

        if not detail or not detail.get("kras"):
            return

        payload = [
            {
                "kra_id": kra["id"],
                "self_rating": random.randint(3, 5),
                "self_comments": "Load test self-rating comment",
            }
            for kra in detail["kras"]
        ]

        self.post_json(
            f"/api/diaries/{diary_id}/self-rating",
            payload,
            name="/api/diaries/{diary_id}/self-rating",
        )
        self.post_json(
            f"/api/diaries/{diary_id}/submit-self-rating",
            name="/api/diaries/{diary_id}/submit-self-rating",
        )

    @task(4)
    def manager_rating(self):
        if self.role != "manager":
            return

        diaries = self.get_json("/api/diaries/team", {"page": 1, "page_size": 25}) or []
        candidates = [
            d for d in diaries
            if d.get("self_status") in ["submitted", "auto_submitted"]
            and d.get("final_status") not in ["baselined", "closed"]
        ]

        if not candidates:
            return

        diary_id = random.choice(candidates)["id"]
        detail = self.get_json(f"/api/diaries/{diary_id}")

        if not detail or not detail.get("kras"):
            return

        payload = [
            {
                "kra_id": kra["id"],
                "mgr_rating": random.randint(3, 5),
                "mgr_comments": "Load test manager-rating comment",
            }
            for kra in detail["kras"]
        ]

        self.post_json(
            f"/api/diaries/{diary_id}/manager-rating",
            payload,
            name="/api/diaries/{diary_id}/manager-rating",
        )
        self.post_json(
            f"/api/diaries/{diary_id}/submit-manager-rating",
            name="/api/diaries/{diary_id}/submit-manager-rating",
        )

    @task(3)
    def approver_actions(self):
        if self.role != "approver":
            return

        diaries = self.get_json("/api/diaries/approver-queue", {"page": 1, "page_size": 25}) or []
        if not diaries:
            return

        diary = random.choice(diaries)
        diary_id = diary["id"]

        if diary.get("kra_status") == "submitted":
            self.post_json(
                f"/api/diaries/{diary_id}/approve-kra",
                {"action": "approve", "comment": "Load test approval"},
                name="/api/diaries/{diary_id}/approve-kra",
            )

        if diary.get("mgr_status") == "submitted" and not diary.get("final_review_open"):
            self.post_json(
                f"/api/diaries/{diary_id}/approve-rating",
                {"action": "approve", "comment": "Load test rating approval"},
                name="/api/diaries/{diary_id}/approve-rating",
            )

    @task(2)
    def manager_final_review(self):
        if self.role != "manager":
            return

        diaries = self.get_json("/api/diaries/team", {"page": 1, "page_size": 25}) or []
        candidates = [
            d for d in diaries
            if d.get("final_review_open") is True
            and d.get("mgr_status") == "submitted"
        ]

        if not candidates:
            return

        diary_id = random.choice(candidates)["id"]
        self.post_json(
            f"/api/diaries/{diary_id}/submit-final-review",
            {
                "overall_performance_rating": random.randint(3, 5),
                "overall_performance_comments": "Overall performance review submitted during load test.",
            },
            name="/api/diaries/{diary_id}/submit-final-review",
        )

    @task(2)
    def grievance_create_and_respond(self):
        if self.role == "reportee":
            self.post_json(
                "/api/grievances",
                {
                    "diary_kra_id": None,
                    "grievance_type": "overall",
                    "description": f"Load test grievance {uuid.uuid4()}",
                },
                name="/api/grievances",
            )

        if self.role in ["manager", "approver"]:
            endpoint = "/api/grievances/team" if self.role == "manager" else "/api/grievances/approver"
            grievances = self.get_json(endpoint, {"page": 1, "page_size": 25}) or []
            open_items = [g for g in grievances if g.get("status") not in ["resolved", "closed"]]

            if not open_items:
                return

            grievance_id = random.choice(open_items)["id"]
            self.post_json(
                f"/api/grievances/{grievance_id}/respond",
                {
                    "response": "Load test grievance response",
                    "resolve": random.choice([False, True]),
                },
                name="/api/grievances/{grievance_id}/respond",
            )

    @task(1)
    def admin_master_data_writes(self):
        # Disabled for sustained mixed-load tests because there is no band
        # delete endpoint, so this task permanently pollutes master data.
        return

    @task(1)
    def admin_dashboard_read(self):
        if self.role == "admin" and self.headers:
            self.client.get("/api/admin/dashboard", headers=self.headers)


class PMSReadUser(HttpUser):
    fixed_count = 500
    wait_time = between(1, 4)

    def on_start(self):
        self.headers = {}
        self.user = weighted_user()
        self.role = self.user["role"]

        with self.client.post(
            "/api/auth/login",
            json={
                "username": self.user["username"],
                "password": self.user["password"],
            },
            catch_response=True,
        ) as res:
            if res.status_code == 200:
                token = res.json()["access_token"]
                self.headers = {"Authorization": f"Bearer {token}"}
                res.success()
            else:
                res.failure(f"{res.status_code}: {res.text[:300]}")

    def get_req(self, path, name=None, params=None):
        if not self.headers:
            return None
        with self.client.get(
            path,
            headers=self.headers,
            name=name or path,
            params=params,
            catch_response=True,
        ) as res:
            if res.status_code == 200:
                res.success()
                try:
                    data = res.json()
                    return data.get("items", data) if isinstance(data, dict) else data
                except Exception:
                    return None
            elif res.status_code in [400, 403, 404]:
                res.success()
            else:
                res.failure(f"{res.status_code}: {res.text[:300]}")
        return None

    @task(5)
    def dashboard_or_diaries(self):
        if self.role == "admin":
            self.get_req("/api/admin/dashboard")
        elif self.role == "reportee":
            diaries = self.get_req("/api/diaries/my", params={"page": 1, "page_size": 25}) or []
            if diaries:
                diary = random.choice(diaries)
                self.get_req(f"/api/diaries/{diary['id']}", name="/api/diaries/{diary_id}")
        elif self.role == "manager":
            diaries = self.get_req("/api/diaries/team", params={"page": 1, "page_size": 25}) or []
            if diaries:
                diary = random.choice(diaries)
                self.get_req(f"/api/diaries/{diary['id']}", name="/api/diaries/{diary_id}")
        elif self.role == "approver":
            diaries = self.get_req("/api/diaries/approver-queue", params={"page": 1, "page_size": 25}) or []
            if diaries:
                diary = random.choice(diaries)
                self.get_req(f"/api/diaries/{diary['id']}", name="/api/diaries/{diary_id}")

    @task(2)
    def grievance_reads(self):
        if self.role == "reportee":
            self.get_req("/api/grievances/my", params={"page": 1, "page_size": 25})
        elif self.role == "manager":
            self.get_req("/api/grievances/team", params={"page": 1, "page_size": 25})
        elif self.role == "approver":
            self.get_req("/api/grievances/approver", params={"page": 1, "page_size": 25})

    @task(1)
    def kra_master_reads(self):
        if self.role in ["manager", "approver"]:
            bands = self.get_req("/api/bands") or []
            if bands:
                band = random.choice(bands)
                self.get_req(
                    "/api/kra-master",
                    name="/api/kra-master?band_id={band_id}",
                    params={"band_id": band["id"]},
                )
