import json
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


def main():
    with notifications_lock:
        notifications.clear()

    # 1) 新建竞赛：使用 endX/endY（服务端兼容字段）
    status_create, comp = post_json(
        "/competitions", {"endX": 10, "endY": 10}, expect_status=201
    )
    assert status_create == 201
    competition_id = comp["competitionId"]

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

    reports = [
        {"competitionId": competition_id, "teamId": "Bravo", "memberId": "N1", "x": 2, "y": 3},
        {
            "competitionId": competition_id,
            "teamId": "Alpha",
            "memberId": "M1",
            "x": 10.4,
            "y": 10.2,
        },
        {
            "competitionId": competition_id,
            "teamId": "Alpha",
            "memberId": "M2",
            "x": 9.2,
            "y": 10.6,
        },
        {
            "competitionId": competition_id,
            "teamId": "Alpha",
            "memberId": "M3",
            "x": 10.1,
            "y": 9.3,
        },
        {
            "competitionId": competition_id,
            "teamId": "Bravo",
            "memberId": "N1",
            "x": 10.0,
            "y": 10.0,
        },
    ]

    for payload in reports:
        _, result = post_json("/reports", payload)
        print(f"[上报结果] {payload['teamId']}/{payload['memberId']} -> {result}")
        time.sleep(0.35)

    # 5) 竞赛结束后：再上报应返回结束信息（即使团队/成员仍可识别）
    status_done, body_done = post_json(
        "/reports",
        {
            "competitionId": competition_id,
            "teamId": "Bravo",
            "memberId": "N2",
            "x": 10,
            "y": 10,
        },
    )
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
