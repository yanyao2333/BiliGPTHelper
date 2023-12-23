# pylint: skip-file
"""根据任务状态记录生成统计信息"""
import json
import os
from collections import Counter

import matplotlib
import matplotlib.pyplot as plt


def run_statistic(output_dir, data):
    if os.getenv("RUNNING_IN_DOCKER") == "yes":
        matplotlib.rcParams["font.sans-serif"] = ["WenQuanYi Zen Hei"]
        matplotlib.rcParams["axes.unicode_minus"] = False  # 用来正常显示负号
    else:
        matplotlib.rcParams["font.sans-serif"] = ["SimHei"]
        matplotlib.rcParams["axes.unicode_minus"] = False

    # Initialize directories and counters
    output_folder = output_dir
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)
    else:
        for file in os.listdir(output_folder):
            os.remove(os.path.join(output_folder, file))

    # Mapping end reasons to readable names
    end_reason_map = {"normal": "正常结束", "error": "错误结束", "noneed": "AI认为不需要摘要"}

    # Initialize variables
    end_reasons = []
    error_reasons = []
    user_ids = []
    request_types = []

    # Populate variables based on task statuses
    if "tasks" not in data or not data["tasks"]:
        return
    for task_id, task in data["tasks"].items():
        end_reason = task.get("end_reason", "normal")
        end_reasons.append(end_reason_map.get(end_reason, "Unknown"))

        error_reason = task.get("error_msg", "正常结束")
        error_reasons.append(error_reason)

        task_data = task.get("data", {})
        user_data = task_data.get("user", None)
        private_msg_event = task_data.get("item", None).get("private_msg_event", None)

        if user_data:
            user_ids.append(user_data.get("mid", "未知"))
        elif private_msg_event:
            user_ids.append(private_msg_event.get("text_event", {}).get("sender_uid", "未知"))

        if private_msg_event:
            request_types.append("私信请求")
        else:
            request_types.append("At 请求")

    # Data Processing
    end_reason_counts = Counter(end_reasons)
    error_reason_counts = Counter(error_reasons)
    user_id_counts = Counter(user_ids)
    request_type_counts = Counter(request_types)

    # Pie Chart for Task End Reasons
    plt.figure(figsize=(4, 4))
    plt.pie(
        list(end_reason_counts.values()),
        labels=list(end_reason_counts.keys()),
        autopct="%1.0f%%",
    )
    plt.title("任务结束原因")
    plt.savefig(f"{output_folder}/任务结束原因饼形图.png")

    # Bar Chart for Error Reasons
    plt.figure(figsize=(8, 4))
    bars = plt.barh(
        list(error_reason_counts.keys()), list(error_reason_counts.values())
    )
    plt.xlabel("数量")
    plt.ylabel("错误原因")
    plt.title("错误原因排名")

    # 设置x轴刻度为整数
    max_value = max(error_reason_counts.values())
    plt.xticks(range(0, max_value + 1))

    # 在柱子顶端添加数据标签
    for bar in bars:
        plt.text(
            bar.get_width(),
            bar.get_y() + bar.get_height() / 2,
            str(int(bar.get_width())),
        )

    plt.tight_layout()

    plt.savefig(f"{output_folder}/错误原因排名竖状图.png")

    # Bar Chart for User Task Counts (Top 10)
    top_10_users = dict(
        sorted(user_id_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    )
    plt.figure(figsize=(8, 4))
    bars = plt.barh(list(map(str, top_10_users.keys())), list(top_10_users.values()))
    plt.xlabel("数量")
    plt.ylabel("用户 ID")
    plt.title("用户发起任务次数排名")
    max_value = max(top_10_users.values())
    plt.xticks(range(0, max_value + 1))
    for bar in bars:
        plt.text(
            bar.get_width() - 0.2,
            bar.get_y() + bar.get_height() / 2,
            str(int(bar.get_width())),
        )
    plt.savefig(f"{output_folder}/用户发起任务次数排名竖状图.png")

    # Pie Chart for Request Types
    plt.figure(figsize=(4, 4))
    plt.pie(
        list(request_type_counts.values()),
        labels=list(request_type_counts.keys()),
        autopct="%1.0f%%",
    )
    plt.title("请求类型占比")
    plt.savefig(f"{output_folder}/请求类型占比饼形图.png")

    def get_pingyu(total_requests):
        if total_requests < 50:
            return "似乎没什么人来找你玩呢，杂鱼❤"
        elif total_requests < 100:
            return "还没被大规模使用，加油！但是...咱才不会鼓励你呢！"
        elif total_requests < 1000:
            return "挖槽，大佬，已经总结这么多次了吗？？？这破程序没出什么bug吧"

    # Markdown Summary
    total_requests = len(data["tasks"])
    md_content = f"""
<h2 align="center">🎉Bilibili-GPT-Helper 运行数据概览🎉</h2>

### 概览

- 总共发起了 {total_requests} 个请求
- 我的评价是：{get_pingyu(total_requests)}

### 图表

#### 任务结束原因
![任务结束原因饼形图](./任务结束原因饼形图.png)

#### 错误原因排名
![错误原因排名竖状图](./错误原因排名竖状图.png)

#### 用户发起任务次数排名
![用户发起任务次数排名竖状图](./用户发起任务次数排名竖状图.png)

#### 请求类型占比
![请求类型占比饼形图](./请求类型占比饼形图.png)
    """

    # Write Markdown content to file
    md_file_path = f"{output_folder}/数据概览.md"
    with open(md_file_path, "w", encoding="utf-8") as f:
        f.write(md_content)


if __name__ == "__main__":
    with open(r"D:\biligpt\records.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    run_statistic(r"../../statistics", data)
