# -*- coding: utf-8 -*-
"""测试大模型管理接口 + 用量记录/费用计算

覆盖：模型 CRUD、activate 切换、usage 统计、record_usage 入库与 compute_cost。
"""
import pytest
from app.database import get_db_ctx
from app.llm import store


@pytest.fixture(autouse=True)
def cleanup():
    """每个测试后清理创建的测试模型与用量记录"""
    yield
    with get_db_ctx() as db:
        db.execute("DELETE FROM model_configs WHERE model_name LIKE 'test_%'")
        db.execute("DELETE FROM usage_logs WHERE model_name LIKE 'test_%'")
        db.commit()


class TestModelCRUD:

    def test_list_models(self, client, admin_headers):
        """获取模型列表成功"""
        resp = client.get("/api/admin/models", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_create_model(self, client, admin_headers):
        """新增模型成功"""
        resp = client.post("/api/admin/models", json={
            "provider": "ali",
            "model_name": "test_qwen_a",
            "display_name": "测试模型A",
            "price_in": 0.001,
            "price_out": 0.002,
            "enabled": True,
        }, headers=admin_headers)
        assert resp.status_code == 201
        data = resp.json()
        assert data["model_name"] == "test_qwen_a"
        assert data["is_active"] is False
        assert data["enabled"] is True

    def test_create_duplicate(self, client, admin_headers):
        """模型名重复返回 400"""
        payload = {
            "provider": "ali",
            "model_name": "test_qwen_dup",
            "display_name": "重复",
            "price_in": 0.001,
            "price_out": 0.002,
        }
        client.post("/api/admin/models", json=payload, headers=admin_headers)
        resp = client.post("/api/admin/models", json=payload, headers=admin_headers)
        assert resp.status_code == 400
        assert "已存在" in resp.json()["detail"]

    def test_update_model(self, client, admin_headers):
        """修改模型单价成功"""
        created = client.post("/api/admin/models", json={
            "provider": "deepseek",
            "model_name": "test_ds_upd",
            "display_name": "待改",
            "price_in": 0.001,
            "price_out": 0.002,
        }, headers=admin_headers).json()

        resp = client.put(f"/api/admin/models/{created['id']}", json={
            "price_in": 0.005,
            "display_name": "已改",
        }, headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["price_in"] == 0.005
        assert data["display_name"] == "已改"

    def test_update_not_found(self, client, admin_headers):
        """修改不存在的模型返回 404"""
        resp = client.put("/api/admin/models/999999", json={"price_in": 1.0},
                          headers=admin_headers)
        assert resp.status_code == 404

    def test_delete_model(self, client, admin_headers):
        """删除模型成功"""
        created = client.post("/api/admin/models", json={
            "provider": "ali",
            "model_name": "test_del",
            "display_name": "待删",
            "price_in": 0.001,
            "price_out": 0.002,
        }, headers=admin_headers).json()
        resp = client.delete(f"/api/admin/models/{created['id']}", headers=admin_headers)
        assert resp.status_code == 200
        # 再删返回 404
        resp = client.delete(f"/api/admin/models/{created['id']}", headers=admin_headers)
        assert resp.status_code == 404

    def test_activate_model(self, client, admin_headers):
        """设为当前模型：目标 is_active=1，其余置 0"""
        m1 = client.post("/api/admin/models", json={
            "provider": "ali", "model_name": "test_act_1",
            "display_name": "A1", "price_in": 0.001, "price_out": 0.002,
        }, headers=admin_headers).json()
        m2 = client.post("/api/admin/models", json={
            "provider": "ali", "model_name": "test_act_2",
            "display_name": "A2", "price_in": 0.001, "price_out": 0.002,
        }, headers=admin_headers).json()

        client.post(f"/api/admin/models/{m1['id']}/activate", headers=admin_headers)
        resp = client.post(f"/api/admin/models/{m2['id']}/activate", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["is_active"] is True

        # m1 应被置为非当前
        listed = client.get("/api/admin/models", headers=admin_headers).json()
        m1_now = next(m for m in listed if m["id"] == m1["id"])
        assert m1_now["is_active"] is False


class TestPermission:

    def test_list_forbidden_for_student(self, client, student_headers):
        """学生无权访问模型管理返回 403"""
        resp = client.get("/api/admin/models", headers=student_headers)
        assert resp.status_code == 403

    def test_list_without_token(self, client):
        """未认证返回 401/403"""
        resp = client.get("/api/admin/models")
        assert resp.status_code in (401, 403)


class TestUsage:

    def test_compute_cost(self, client, admin_headers):
        """按单价计算费用正确"""
        client.post("/api/admin/models", json={
            "provider": "ali", "model_name": "test_cost",
            "display_name": "计费", "price_in": 0.002, "price_out": 0.008,
        }, headers=admin_headers)
        # 1000 输入 * 0.002/千 + 500 输出 * 0.008/千 = 0.002 + 0.004 = 0.006
        cost = store.compute_cost("test_cost", 1000, 500)
        assert cost == pytest.approx(0.006)

    def test_record_usage_and_stats(self, client, admin_headers):
        """记录用量后统计可见"""
        client.post("/api/admin/models", json={
            "provider": "ali", "model_name": "test_usage",
            "display_name": "用量", "price_in": 0.001, "price_out": 0.002,
        }, headers=admin_headers)

        store.record_usage("test_usage", 1, None, 100, 50)

        resp = client.get("/api/admin/models/usage?days=7", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_tokens"] >= 150
        assert len(data["daily"]) == 7
        names = [m["model_name"] for m in data["by_model"]]
        assert "test_usage" in names

    def test_record_usage_task_type(self, client, admin_headers):
        """task_type 落库：缺省 chat，显式传 exam（v4.0-M2）"""
        client.post("/api/admin/models", json={
            "provider": "ali", "model_name": "test_task_type",
            "display_name": "任务类型", "price_in": 0.001, "price_out": 0.002,
        }, headers=admin_headers)

        store.record_usage("test_task_type", 1, None, 10, 5)  # 缺省 chat
        store.record_usage("test_task_type", 1, None, 20, 8, task_type="exam")

        with get_db_ctx() as db:
            cursor = db.execute(
                "SELECT task_type, prompt_tokens FROM usage_logs "
                "WHERE model_name = 'test_task_type' ORDER BY id"
            )
            rows = list(cursor.fetchall())
        assert [r["task_type"] for r in rows] == ["chat", "exam"]
        assert rows[1]["prompt_tokens"] == 20

    def test_usage_days_param(self, client, admin_headers):
        """days 参数控制趋势天数"""
        resp = client.get("/api/admin/models/usage?days=3", headers=admin_headers)
        assert resp.status_code == 200
        assert len(resp.json()["daily"]) == 3
