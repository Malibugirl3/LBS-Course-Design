from __future__ import annotations

import json
import math
import random
import threading
import time

import requests

BASE_URL = "http://127.0.0.1:3000"

notifications = []
notifications_lock = threading.Lock()


def record_notification(team_id, member_id, event, payload):
    with notifications_lock:
        notifications.append(
            {
                "teamId": team_id,
                "memberId": member_id,
                "event": event,
                "payload": payload,
            }
        )


def start_listener(competition_id, team_id, member_id):
    def worker():
        url = f"{BASE_URL}/competitions/{competition_id}/stream"
        try:
            with requests.get(
                url,
                params={"teamId": team_id, "memberId": member_id},
                stream=True,
                timeout=60,
            ) as response:
                response.raise_for_status()
                current_event = None

                for raw_line in response.iter_lines(decode_unicode=True):
                    if not raw_line:
                        continue
                    if raw_line.startswith(":"):
                        continue
                    if raw_line.startswith("event:"):
                        current_event = raw_line.split(":", 1)[1].strip()
                    elif raw_line.startswith("data:"):
                        payload = json.loads(raw_line.split(":", 1)[1].strip())
                        print(f"[通知] {team_id}/{member_id} <- {current_event}: {payload}")
                        record_notification(team_id, member_id, current_event, payload)
                        if current_event == "competition-finished":
                            break
        except Exception as exc:
            print(f"[通知异常] {team_id}/{member_id}: {exc}")

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return thread


def post_json(path, payload, expect_status=None):
    response = requests.post(f"{BASE_URL}{path}", json=payload, timeout=10)
    try:
        data = response.json()
    except Exception:
        data = {"_raw": response.text}
    print(f"POST {path} -> {response.status_code} {data}")
    if expect_status is not None and response.status_code != expect_status:
        raise AssertionError(f"期望状态码 {expect_status}，实际 {response.status_code}")
    return response.status_code, data


def get_json(path, expect_status=None):
    response = requests.get(f"{BASE_URL}{path}", timeout=10)
    data = response.json()
    print(f"GET  {path} -> {response.status_code} {data}")
    if expect_status is not None and response.status_code != expect_status:
        raise AssertionError(f"期望状态码 {expect_status}，实际 {response.status_code}")
    return response.status_code, data


def random_point_far_from_target(tx: float, ty: float) -> tuple[float, float]:
    """在终点外随机生成起点（极坐标）。"""
    angle = random.random() * 2 * math.pi
    dist = random.uniform(12.0, 22.0)
    return tx + dist * math.cos(angle), ty + dist * math.sin(angle)


def random_step_toward(
    x: float, y: float, tx: float, ty: float
) -> tuple[float, float]:
    """
    沿「当前点 -> 终点」方向走随机步长，并加垂直方向的随机扰动，
    模拟朝目标前进但带噪声的轨迹。
    """
    dx, dy = tx - x, ty - y
    dist = math.hypot(dx, dy)
    if dist < 1e-9:
        return x + random.uniform(-0.2, 0.2), y + random.uniform(-0.2, 0.2)

    step = random.uniform(0.9, 2.8)
    step = min(step, dist * random.uniform(0.35, 0.95))

    nx = x + (dx / dist) * step
    ny = y + (dy / dist) * step

    px, py = -dy / dist, dx / dist
    noise = random.uniform(-1.0, 1.0)
    nx += px * noise
    ny += py * noise
    return nx, ny


def advance_position(
    positions: dict, team_id: str, member_id: str, tx: float, ty: float
) -> tuple[float, float]:
    key = (team_id, member_id)
    if key not in positions:
        positions[key] = random_point_far_from_target(tx, ty)
    cur_x, cur_y = positions[key]
    nxt_x, nxt_y = random_step_toward(cur_x, cur_y, tx, ty)
    positions[key] = (nxt_x, nxt_y)
    return nxt_x, nxt_y


def post_report_at(
    competition_id: str, team_id: str, member_id: str, x: float, y: float
):
    payload = {
        "competitionId": competition_id,
        "teamId": team_id,
        "memberId": member_id,
        "x": x,
        "y": y,
    }
    return post_json("/reports", payload)


def march_member_until_arrives(
    competition_id: str,
    team_id: str,
    member_id: str,
    tx: float,
    ty: float,
    positions: dict,
    max_steps: int = 50,
    pause_sec: float = 0.35,
):
    """
    多次随机朝终点迈步并上报，直到该成员本次首次进入终点圈（memberArrivedNow）
    或竞赛已结束。
    """
    for i in range(max_steps):
        x, y = advance_position(positions, team_id, member_id, tx, ty)
        _, result = post_report_at(competition_id, team_id, member_id, x, y)
        print(
            f"[朝目标随机迈步 {i + 1}] {team_id}/{member_id} "
            f"-> ({x:.3f}, {y:.3f}) | 响应: {result.get('message', result)}"
        )
        time.sleep(pause_sec)
        if result.get("status") == "已结束":
            return result
        if result.get("memberArrivedNow"):
            return result
    raise AssertionError(
        f"{team_id}/{member_id} 在 {max_steps} 步内仍未进入终点圈，请调大步长或上限"
    )


def main():
    with notifications_lock:
        notifications.clear()

    # 1) 新建竞赛：使用 endX/endY（服务端兼容字段）
    status_create, comp = post_json(
        "/competitions", {"endX": 10, "endY": 10}, expect_status=201
    )
    assert status_create == 201
    competition_id = comp["competitionId"]
    target = comp["target"]
    tx, ty = float(target["x"]), float(target["y"])

    positions: dict[tuple[str, str], tuple[float, float]] = {}

    # 2) 创建团队
    post_json(f"/competitions/{competition_id}/teams", {"teamId": "Alpha"}, 201)
    post_json(f"/competitions/{competition_id}/teams", {"teamId": "Bravo"}, 201)

    # 3) 重复团队应失败
    status_dup, body_dup = post_json(
        f"/competitions/{competition_id}/teams", {"teamId": "Alpha"}
    )
    assert status_dup == 400, "重复 teamId 应返回 400"
    assert "error" in body_dup

    # 4) 缺参上报
    status_bad, body_bad = post_json("/reports", {"competitionId": competition_id})
    assert status_bad == 400
    assert "error" in body_bad

    listeners = [
        start_listener(competition_id, "Alpha", "M1"),
        start_listener(competition_id, "Alpha", "M2"),
        start_listener(competition_id, "Alpha", "M3"),
        start_listener(competition_id, "Bravo", "N1"),
    ]

    time.sleep(1)

    # 5) Bravo 先随便朝终点走一步（多半仍在圈外），再 Alpha 三人轮流各走到「进圈」
    bx, by = advance_position(positions, "Bravo", "N1", tx, ty)
    _, bravo_first = post_report_at(competition_id, "Bravo", "N1", bx, by)
    print(f"[先手 Bravo] N1 -> ({bx:.3f}, {by:.3f}) | {bravo_first}")
    time.sleep(0.35)

    for mid in ("M1", "M2", "M3"):
        march_member_until_arrives(
            competition_id, "Alpha", mid, tx, ty, positions, max_steps=50, pause_sec=0.35
        )

    # 竞赛应已由 Alpha 夺标结束；Bravo 再报一次仅验证「已结束」响应
    bx2, by2 = advance_position(positions, "Bravo", "N1", tx, ty)
    _, bravo_after = post_report_at(competition_id, "Bravo", "N1", bx2, by2)
    print(f"[结束后 Bravo] N1 -> ({bx2:.3f}, {by2:.3f}) | {bravo_after}")

    # 6) 竞赛结束后：再上报应返回结束信息（即使团队/成员仍可识别）
    nx, ny = advance_position(positions, "Bravo", "N2", tx, ty)
    status_done, body_done = post_report_at(competition_id, "Bravo", "N2", nx, ny)
    assert status_done == 200
    assert body_done.get("winnerTeamId") == "Alpha"
    assert body_done.get("status") == "已结束"

    get_json(f"/competitions/{competition_id}/target")
    get_json(f"/competitions/{competition_id}/status")

    time.sleep(2)
    print(f"监听线程数: {len(listeners)}")

    with notifications_lock:
        finished = [n for n in notifications if n["event"] == "competition-finished"]
        print(f"SSE 收到 competition-finished 次数: {len(finished)}")
        if len(finished) < 1:
            print("警告：未收到结束通知，请确认服务端已启动且未被防火墙拦截。")

    print("测试结束，断言通过。")


if __name__ == "__main__":
    main()
