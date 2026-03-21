#!/usr/bin/env python3
import time

import boto3
import requests

from config import (
    AMI_ID,
    AWS_REGION,
    CHECK_INTERVAL,
    INSTANCE_NAME_TAG,
    INSTANCE_TYPE,
    KEY_NAME,
    PROMETHEUS_URL,
    SECURITY_GROUP,
    THRESHOLD,
)

SCALED = False


def query_prometheus(promql):
    resp = requests.get(PROMETHEUS_URL, params={"query": promql}, timeout=10)
    resp.raise_for_status()
    result = resp.json()["data"]["result"]
    if result:
        return float(result[0]["value"][1])
    return 0.0


def get_cpu_usage():
    q = '100 - (avg(rate(node_cpu_seconds_total{mode="idle"}[2m])) * 100)'
    return query_prometheus(q)


def get_memory_usage():
    q = '(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100'
    return query_prometheus(q)


def launch_ec2():
    ec2 = boto3.client("ec2", region_name=AWS_REGION)
    user_data = """#!/bin/bash
apt update && apt install -y python3 python3-pip
pip3 install flask
cat <<'APP_EOF' > /home/ubuntu/app.py
from flask import Flask
app = Flask(__name__)

@app.route("/")
def home():
    return "Running on AWS Cloud - Auto-Scaled!"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
APP_EOF
python3 /home/ubuntu/app.py &
"""

    response = ec2.run_instances(
        ImageId=AMI_ID,
        InstanceType=INSTANCE_TYPE,
        KeyName=KEY_NAME,
        SecurityGroupIds=[SECURITY_GROUP],
        MinCount=1,
        MaxCount=1,
        UserData=user_data,
        TagSpecifications=[
            {
                "ResourceType": "instance",
                "Tags": [{"Key": "Name", "Value": INSTANCE_NAME_TAG}],
            }
        ],
    )

    instance_id = response["Instances"][0]["InstanceId"]
    print(f"Launched EC2 instance: {instance_id}")
    return instance_id


if __name__ == "__main__":
    print("Monitoring started...")
    while True:
        try:
            cpu = get_cpu_usage()
            mem = get_memory_usage()
            print(f"CPU: {cpu:.1f}% | Memory: {mem:.1f}%")

            if (cpu > THRESHOLD or mem > THRESHOLD) and not SCALED:
                print("THRESHOLD EXCEEDED - Launching AWS EC2 instance...")
                launch_ec2()
                SCALED = True
                print("Cloud burst complete. Traffic can now be routed to EC2.")
        except Exception as exc:
            print(f"Monitor error: {exc}")

        time.sleep(CHECK_INTERVAL)
