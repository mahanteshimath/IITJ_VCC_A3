Below is a complete, end-to-end walkthrough that takes you from a bare VirtualBox install to a working cloud-bursting demo with Prometheus, Grafana, and an auto-scaling Python script that spins up an AWS EC2 instance when local load exceeds 75%.

***

## Step 1 — Create the Local Ubuntu VM in VirtualBox

1. Download and install **VirtualBox** from [virtualbox.org](https://www.virtualbox.org). [scribd](https://www.scribd.com/document/893936761/CC-LAB-MANUAL-1-1)
2. Download an **Ubuntu 22.04 LTS** (or newer) ISO from [ubuntu.com](https://ubuntu.com/download/desktop).
3. In VirtualBox, click **New** -> name the VM (e.g. `hybrid-cloud`) -> Type: Linux, Version: Ubuntu (64-bit).
4. Allocate **2 GB+ RAM** and create a **20 GB virtual hard disk** (VDI, dynamically allocated). [scribd](https://www.scribd.com/document/893936761/CC-LAB-MANUAL-1-1)
5. Under **Settings -> Network**, set Adapter 1 to **Bridged Adapter** (so the VM gets an IP on your LAN) or use NAT with port-forwarding for ports `5000, 9090, 9100, 3000`.
6. Start the VM, select the Ubuntu ISO, and complete the install. After install, run:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv curl wget git
```

***

## Step 2 — Deploy the Flask Application

Create a minimal Flask app that will serve as your "baseline workload."

```bash
mkdir ~/flask-app && cd ~/flask-app
python3 -m venv venv
source venv/bin/activate
pip install flask
```

Create **`app.py`**:

```python
from flask import Flask

app = Flask(__name__)

@app.route("/")
def home():
	return "<h1>Running on Local VM - Baseline Workload</h1>"

if __name__ == "__main__":
	app.run(host="0.0.0.0", port=5000)
```

Start it in the background:

```bash
nohup python3 app.py &
```

Verify: `curl http://localhost:5000` should return the HTML heading. [dev](https://dev.to/jj_dev/use-user-data-script-run-a-flask-app-im3)

***

## Step 3 — Install and Configure Node Exporter

Node Exporter exposes hardware metrics (CPU, memory, disk, network) on port **9100**. [youtube](https://www.youtube.com/watch?v=Jo1vn5mpn7U)

```bash
# Create a dedicated user
sudo useradd --system --no-create-home --shell /bin/false node_exporter

# Download (check https://github.com/prometheus/node_exporter/releases for latest)
wget https://github.com/prometheus/node_exporter/releases/download/v1.8.1/node_exporter-1.8.1.linux-amd64.tar.gz
tar xvfz node_exporter-1.8.1.linux-amd64.tar.gz
sudo mv node_exporter-1.8.1.linux-amd64/node_exporter /usr/local/bin/
rm -rf node_exporter-1.8.1.linux-amd64*
```

Create the systemd service - **`/etc/systemd/system/node_exporter.service`**:

```ini
[Unit]
Description=Node Exporter
Wants=network-online.target
After=network-online.target

[Service]
User=node_exporter
Group=node_exporter
Type=simple
Restart=on-failure
RestartSec=5s
ExecStart=/usr/local/bin/node_exporter

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now node_exporter
```

Verify: `curl http://localhost:9100/metrics` should return a wall of metrics text. [scribd](https://www.scribd.com/document/800568752/prome-installation)

***

## Step 4 — Install and Configure Prometheus

Prometheus scrapes Node Exporter every 10 seconds and stores time-series data. [scribd](https://www.scribd.com/document/800568752/prome-installation)

```bash
sudo useradd --system --no-create-home --shell /bin/false prometheus
sudo mkdir -p /etc/prometheus /var/lib/prometheus

wget https://github.com/prometheus/prometheus/releases/download/v2.53.0/prometheus-2.53.0.linux-amd64.tar.gz
tar xvfz prometheus-2.53.0.linux-amd64.tar.gz
cd prometheus-2.53.0.linux-amd64

sudo mv prometheus promtool /usr/local/bin/
sudo mv consoles console_libraries /etc/prometheus/
cd .. && rm -rf prometheus-2.53.0.linux-amd64*
```

Create **`/etc/prometheus/prometheus.yml`**:

```yaml
global:
  scrape_interval: 10s

scrape_configs:
  - job_name: "prometheus"
	static_configs:
	  - targets: ["localhost:9090"]

  - job_name: "node_exporter"
	static_configs:
	  - targets: ["localhost:9100"]
```

Create the systemd service - **`/etc/systemd/system/prometheus.service`**:

```ini
[Unit]
Description=Prometheus
Wants=network-online.target
After=network-online.target

[Service]
User=prometheus
Group=prometheus
Type=simple
Restart=on-failure
RestartSec=5s
ExecStart=/usr/local/bin/prometheus \
  --config.file=/etc/prometheus/prometheus.yml \
  --storage.tsdb.path=/var/lib/prometheus \
  --web.console.templates=/etc/prometheus/consoles \
  --web.console.libraries=/etc/prometheus/console_libraries \
  --web.listen-address=0.0.0.0:9090

[Install]
WantedBy=multi-user.target
```

Set permissions and start:

```bash
sudo chown -R prometheus:prometheus /etc/prometheus /var/lib/prometheus
sudo systemctl daemon-reload
sudo systemctl enable --now prometheus
```

Verify: browse to `http://<VM_IP>:9090` -> Status -> Targets — both jobs should show **UP**. [scribd](https://www.scribd.com/document/800568752/prome-installation)

***

## Step 5 — Install and Configure Grafana

```bash
sudo apt install -y apt-transport-https software-properties-common
wget -q -O - https://apt.grafana.com/gpg.key | sudo gpg --dearmor -o /usr/share/keyrings/grafana.gpg
echo "deb [signed-by=/usr/share/keyrings/grafana.gpg] https://apt.grafana.com stable main" | \
  sudo tee /etc/apt/sources.list.d/grafana.list
sudo apt update && sudo apt install -y grafana
sudo systemctl enable --now grafana-server
```

1. Open `http://<VM_IP>:3000` — default login is **admin / admin**. [scribd](https://www.scribd.com/document/800568752/prome-installation)
2. Go to **Connections -> Data Sources -> Add data source -> Prometheus**.
3. Set URL to `http://localhost:9090` and click **Save & Test**.
4. Import dashboard: go to **Dashboards -> Import -> ID `1860`** (Node Exporter Full) -> select the Prometheus data source -> **Import**. [community.grafana](https://community.grafana.com/t/node-exporter-full-related-questions/27385)

You now have real-time CPU and memory graphs.

***

## Step 6 — Configure AWS Prerequisites

Before writing the auto-scale script you need a few AWS resources:

1. **AWS Account** with an IAM user that has `AmazonEC2FullAccess` (or a tighter custom policy).
2. **AWS CLI configured** on the VM:
   ```bash
   sudo apt install -y awscli
   aws configure
   # Enter: Access Key, Secret Key, Region (e.g. ap-south-1), output format (json)
   ```
3. **A Key Pair** — create one in the EC2 console (e.g. `hybrid-key`) and download the `.pem` file.
4. **A Security Group** — allow inbound TCP **port 5000** (and 22 for SSH) from `0.0.0.0/0`. Note its **Security Group ID** (e.g. `sg-0abc123`).
5. **An AMI ID** for Ubuntu in your region (e.g. `ami-0abcdef1234567890`). Find the latest Ubuntu AMI in the EC2 Launch wizard. [oneuptime](https://oneuptime.com/blog/post/2026-02-12-manage-ec2-instances-boto3/view)
6. Install Boto3 on the VM:
   ```bash
   pip install boto3 requests
   ```

***

## Step 7 — Write the Monitor-and-Scale Script

Create **`~/monitor_and_scale.py`** — this is the heart of the cloud-bursting logic: [gazerad](https://gazerad.com/en/article/automatically-scale-an-application-with-an-azure-hybrid-cloud-part-1-the-infrastructure)

```python
#!/usr/bin/env python3
import time
import requests
import boto3

# ─── Configuration ───────────────────────────────────────────────
PROMETHEUS_URL   = "http://localhost:9090"
THRESHOLD        = 75.0          # percent
CHECK_INTERVAL   = 30            # seconds
AWS_REGION       = "ap-south-1"  # change to your region
AMI_ID           = "ami-0abcdef1234567890"  # Ubuntu AMI in your region
INSTANCE_TYPE    = "t2.micro"
KEY_NAME         = "hybrid-key"
SECURITY_GROUP   = "sg-0abc123"  # your SG ID
# ─────────────────────────────────────────────────────────────────

# UserData script that the EC2 instance runs on first boot
USER_DATA = """#!/bin/bash
apt update -y
apt install -y python3 python3-pip python3-venv
mkdir -p /home/ubuntu/app && cd /home/ubuntu/app
python3 -m venv venv
source venv/bin/activate
pip install flask
cat <<'PYEOF' > app.py
from flask import Flask
app = Flask(__name__)

@app.route("/")
def home():
	return "<h1>Running on AWS Cloud - Auto-Scaled!</h1>"

if __name__ == "__main__":
	app.run(host="0.0.0.0", port=5000)
PYEOF
nohup python3 app.py > /var/log/flask.log 2>&1 &
"""

ec2_client = boto3.client("ec2", region_name=AWS_REGION)
launched_instance_id = None


def query_prometheus(promql: str) -> float:
	"""Run a PromQL instant query and return the scalar result."""
	resp = requests.get(
		f"{PROMETHEUS_URL}/api/v1/query",
		params={"query": promql},
	)
	result = resp.json()["data"]["result"]
	if result:
		return float(result[0]["value"] [scribd](https://www.scribd.com/document/893936761/CC-LAB-MANUAL-1-1))
	return 0.0


def get_cpu_usage() -> float:
	q = '100 - (avg(rate(node_cpu_seconds_total{mode="idle"}[2m])) * 100)'
	return query_prometheus(q)


def get_memory_usage() -> float:
	q = "(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100"
	return query_prometheus(q)


def launch_ec2():
	global launched_instance_id
	print(">>> Launching EC2 instance ...")
	response = ec2_client.run_instances(
		ImageId=AMI_ID,
		InstanceType=INSTANCE_TYPE,
		KeyName=KEY_NAME,
		SecurityGroupIds=[SECURITY_GROUP],
		MinCount=1,
		MaxCount=1,
		UserData=USER_DATA,
		TagSpecifications=[
			{
				"ResourceType": "instance",
				"Tags": [{"Key": "Name", "Value": "hybrid-auto-scaled"}],
			}
		],
	)
	launched_instance_id = response["Instances"][0]["InstanceId"]
	print(f">>> EC2 instance launched: {launched_instance_id}")


def main():
	global launched_instance_id
	print("Monitor started — checking every", CHECK_INTERVAL, "seconds")
	while True:
		cpu = get_cpu_usage()
		mem = get_memory_usage()
		print(f"CPU: {cpu:.1f}%  |  Memory: {mem:.1f}%")

		if (cpu > THRESHOLD or mem > THRESHOLD) and launched_instance_id is None:
			print(f"!!! Threshold breached (CPU={cpu:.1f}%, MEM={mem:.1f}%) — scaling out")
			launch_ec2()
		elif launched_instance_id:
			print(f"    EC2 already running: {launched_instance_id}")

		time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
	main()
```

Make it executable and run:

```bash
chmod +x ~/monitor_and_scale.py
python3 ~/monitor_and_scale.py
```

The script queries Prometheus every 30 seconds. If either CPU or memory exceeds 75% and no instance is already running, it calls `run_instances` via Boto3. The EC2 instance bootstraps Flask through the `UserData` script. [docs.aws.amazon](https://docs.aws.amazon.com/boto3/latest/reference/services/ec2/client/run_instances.html)

***

## Step 8 — Simulate Load to Trigger Scaling

Open a second terminal on the VM and stress the CPU:

```bash
sudo apt install -y stress
# Spike all CPU cores for 120 seconds
stress --cpu $(nproc) --timeout 120
```

Within 30–60 seconds you should see the monitor script detect CPU > 75% and launch the EC2 instance. Watch the Grafana dashboard to see the spike visually. [youtube](https://www.youtube.com/watch?v=Jo1vn5mpn7U)

***

## Step 9 — Verify the AWS Burst Instance

1. In the **AWS EC2 Console**, find the instance tagged `hybrid-auto-scaled` and note its **Public IP**.
2. Wait 2–3 minutes for UserData to finish, then browse to `http://<EC2_PUBLIC_IP>:5000`.
3. You should see: **"Running on AWS Cloud – Auto-Scaled!"**

***

## Step 10 — (Optional) Scale-In / Terminate

Add a scale-in block to `monitor_and_scale.py` so that when both metrics drop below a lower threshold (e.g. 40%) the burst instance is terminated: [oneuptime](https://oneuptime.com/blog/post/2026-02-12-manage-ec2-instances-boto3/view)

```python
SCALE_IN_THRESHOLD = 40.0

# Inside the main loop, after the elif:
if launched_instance_id and cpu < SCALE_IN_THRESHOLD and mem < SCALE_IN_THRESHOLD:
	print("<<< Load normalized — terminating EC2 instance")
	ec2_client.terminate_instances(InstanceIds=[launched_instance_id])
	launched_instance_id = None
```

***

## Quick Reference — Ports & Services

| Service        | Port  | Purpose                          |
|----------------|-------|----------------------------------|
| Flask App      | 5000  | Web application (local + cloud)  |
| Node Exporter  | 9100  | Exposes OS-level metrics         |
| Prometheus     | 9090  | Scrapes & stores time-series     |
| Grafana        | 3000  | Visualization dashboards         |

This setup demonstrates the **cloud-bursting pattern**: your baseline workload runs entirely on the local VM, and only when resource pressure exceeds the threshold does the system automatically offload to AWS — keeping cloud costs near zero during normal operation. [gazerad](https://gazerad.com/en/article/automatically-scale-an-application-with-an-azure-hybrid-cloud-part-1-the-infrastructure)
