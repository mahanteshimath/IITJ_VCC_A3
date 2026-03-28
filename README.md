# Hybrid Cloud Auto-Scale (Local VM to AWS)

> **Cloud bursting pattern**: baseline workloads run on a local VM; when CPU or memory exceeds 75 %, an AWS EC2 instance is launched automatically to absorb the overflow.

## Architecture Design

```
┌────────────────────────────────────────────────────────┐
│                   Local Ubuntu VM                      │
│                                                        │
│  ┌──────────┐   ┌──────────────┐   ┌───────────────┐  │
│  │ Flask App │   │ Node Exporter│   │   Grafana     │  │
│  │  :5000    │   │    :9100     │   │    :3000      │  │
│  └──────────┘   └──────┬───────┘   └───────────────┘  │
│                         │ metrics                      │
│                  ┌──────▼───────┐                      │
│                  │  Prometheus  │                      │
│                  │    :9090     │                      │
│                  └──────┬───────┘                      │
│                         │ queried every 30 s           │
│                  ┌──────▼───────┐                      │
│                  │ monitor_and_ │                      │
│                  │  scale.py    │                      │
│                  └──────┬───────┘                      │
└─────────────────────────┼──────────────────────────────┘
                          │ CPU or RAM > 75 %
                          ▼
              ┌───────────────────────┐
              │   AWS EC2 (t2.micro)  │
              │   Flask App  :5000    │
              │   "Running on AWS     │
              │    Cloud - Auto-      │
              │    Scaled!"           │
              └───────────────────────┘
```

<img width="1338" height="1622" alt="mermaid-diagram-2026-03-29-035717" src="https://github.com/user-attachments/assets/635b9231-c2d8-46b5-8683-d6e8f431baa2" />


**How it works, end-to-end:**

1. **Node Exporter** exposes hardware metrics (CPU, memory, disk, network) on port `9100`.
2. **Prometheus** scrapes those metrics every **10 seconds** and stores them as time-series data.
3. **`monitor_and_scale.py`** queries Prometheus every **30 seconds** using two PromQL expressions:
   - CPU: `100 - (avg(rate(node_cpu_seconds_total{mode="idle"}[2m])) * 100)`
   - Memory: `(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100`
4. If **either** metric exceeds **75 %** and no instance has been launched yet, the script calls AWS Boto3 `run_instances` to spin up a **t2.micro** EC2 instance.
5. The EC2 instance bootstraps itself via **UserData** — it installs Python/Flask and starts a copy of the web app on port 5000.
6. **Grafana** provides a visual dashboard of CPU and memory in real time so you can watch the burst happen.

Generated architecture diagram: [docs/hybrid_cloud_architecture.png](docs/hybrid_cloud_architecture.png)

---

## Prerequisites

Before starting, make sure you have:

| Requirement | Details |
|---|---|
| **Host machine** | Windows, macOS, or Linux with at least 8 GB RAM (4 GB left for the host after the VM) |
| **VirtualBox** | Version 7.x — download from <https://www.virtualbox.org/wiki/Downloads> |
| **Ubuntu 22.04 ISO** | Download from <https://releases.ubuntu.com/22.04/> (Desktop or Server) |
| **AWS Account** | Free-tier eligible account — <https://aws.amazon.com/free/> |
| **AWS CLI** | Installed on the VM — instructions below |
| **Git** | To clone this repository |

---

## Repository Structure

```text
.
├── README.md                          ← You are here
├── app/
│   └── app.py                         ← Minimal Flask web app (runs on local VM)
├── autoscale/
│   ├── config.py                      ← All tuneable parameters (thresholds, AWS settings)
│   ├── monitor_and_scale.py           ← Core script: polls Prometheus → launches EC2
│   └── requirements.txt               ← Python dependencies (boto3, requests, flask)
├── monitoring/
│   ├── prometheus.yml                 ← Prometheus scrape config (Node Exporter target)
│   ├── node_exporter.service          ← systemd unit file for Node Exporter
│   └── grafana-dashboard.json         ← Custom Grafana dashboard (CPU + Memory panels)
├── docs/
│   ├── setup-guide.md                 ← Detailed setup walkthrough
│   └── hybrid_cloud_architecture.png  ← Architecture diagram
└── stress-test/
    └── load_test.sh                   ← Stress script to trigger auto-scaling
```

---

## Step-by-Step Implementation

### Step 1: Create a Local VM in VirtualBox

1. **Download & install VirtualBox** from <https://www.virtualbox.org/wiki/Downloads>.
2. **Download Ubuntu 22.04 ISO** from <https://releases.ubuntu.com/22.04/>.
3. **Create a new VM** in VirtualBox with these settings:

   | Setting | Value |
   |---|---|
   | Name | `mh-vm1` |
   | Type / Version | Linux / Ubuntu (64-bit) |
   | CPUs | **1** (minimum — needed to generate meaningful CPU metrics) |
   | RAM | **8192 MB** (8 GB minimum) |
   | Disk | **25 GB** (dynamically allocated VDI) |


![alt text](mh-vm1-config.png)


4. **Attach the ISO** to the VM's optical drive and boot it.
5. **Install Ubuntu** — follow the installer defaults; create a user (e.g., `ubuntu`).
6. **Configure Networking**:
   - Shut down the VM → Settings → Network → Adapter 1 → change **Attached to** from `NAT` to **Bridged Adapter**.
   - Select your host's active network adapter (Wi-Fi or Ethernet).
   - Boot the VM again.
7. **Verify networking** from inside the VM:

   ```bash
   ip addr show          # note the IP address (e.g., 192.168.56.10 )
   ping -c 3 google.com  # confirm internet access
   ```

8. **Update the system and install base packages**:

   ```bash
   sudo apt update && sudo apt upgrade -y
   sudo apt install -y python3 python3-pip curl wget net-tools git stress
   ```
 ![alt text](ip-internet.png)

9. **Clone this repository** inside the VM:

   ```bash
   git clone https://github.com/mahanteshimath/IITJ_VCC_A3.git
   cd IITJ_VCC_A3
   ```

---

### Step 2: Install & Configure Node Exporter

Node Exporter exposes hardware metrics that Prometheus will scrape.

```bash
# Download Node Exporter v1.8.2 (latest stable)
wget https://github.com/prometheus/node_exporter/releases/download/v1.8.2/node_exporter-1.8.2.linux-amd64.tar.gz

# Extract and install the binary
tar -xvf node_exporter-1.8.2.linux-amd64.tar.gz
sudo mv node_exporter-1.8.2.linux-amd64/node_exporter /usr/local/bin/

# Create a dedicated system user (no login shell, no home dir)
sudo useradd -rs /bin/false node_exporter

# Copy the systemd service file from this repo
sudo cp monitoring/node_exporter.service /etc/systemd/system/node_exporter.service

# Enable and start the service
sudo systemctl daemon-reload
sudo systemctl enable --now node_exporter
```
![alt text](node-install.png)
**Verify it works:**

```bash
# Check service status — should show "active (running)"
sudo systemctl status node_exporter

# Fetch a metric — should return text with lines like node_cpu_seconds_total
curl -s http://localhost:9100/metrics | head -20
```

![alt text](node-success1.png)

> If `curl` shows metrics output, Node Exporter is running correctly.


---

### Step 3: Install & Configure Prometheus

Prometheus scrapes Node Exporter every 10 seconds and stores the time-series data.

```bash
# Download Prometheus v2.48.0
wget https://github.com/prometheus/prometheus/releases/download/v2.48.0/prometheus-2.48.0.linux-amd64.tar.gz

# Extract and move to /opt
tar -xvf prometheus-2.48.0.linux-amd64.tar.gz
sudo mv prometheus-2.48.0.linux-amd64 /opt/prometheus

# Copy the config from this repo (scrapes localhost:9100 every 10s)
sudo cp monitoring/prometheus.yml /opt/prometheus/prometheus.yml
```

**Optional: download Prometheus on Windows host and use in Ubuntu VM**


```bash
cd ~/IITJ_VCC_A3/prometheus
tar -xvf prometheus-2.48.0.linux-amd64.tar.gz
sudo mv prometheus-2.48.0.linux-amd64 /opt/prometheus
sudo cp ~/IITJ_VCC_A3/monitoring/prometheus.yml /opt/prometheus/prometheus.yml
pkill prometheus || true
cd /opt/prometheus && ./prometheus &
```
![alt text](pro-success.png)
**Create or overwrite from terminal (Ubuntu VM):**

Go to repo root:

```bash
cd ~/IITJ_VCC_A3
```

Ensure folder exists:

```bash
mkdir -p monitoring
```

Create or replace file:

```bash
cat > monitoring/prometheus.yml << 'EOF'
global:
  scrape_interval: 10s

scrape_configs:
  - job_name: 'node'
    static_configs:
      - targets: ['localhost:9100']
EOF


sudo cp monitoring/prometheus.yml /opt/prometheus/prometheus.yml

# Start or restart Prometheus
pkill prometheus || true
cd /opt/prometheus && ./prometheus &

```


**Line-by-line explanation:**

1. `global:` defines default behavior for all scrape jobs unless overridden later.
2. `scrape_interval: 10s` tells Prometheus to pull fresh metrics every 10 seconds.
3. `scrape_configs:` starts the list of metric collection jobs.
4. `job_name: 'node'` creates a logical label (`job="node"`) used in PromQL and Grafana filters.
5. `static_configs:` means targets are manually defined (not auto-discovered).
6. `targets: ['localhost:9100']` points to Node Exporter running on the same VM at port 9100.

**Why these values are used in this project:**

1. A 10-second scrape gives enough resolution to catch short CPU spikes from the stress test.
2. `localhost` is correct because Prometheus and Node Exporter are both on the same VM.
3. One simple static target keeps setup easy and reproducible for assignment/demo use.

**How this impacts your dashboards and auto-scale script:**

1. Grafana panels read the same time-series data collected by this config.
2. `autoscale/monitor_and_scale.py` queries Prometheus API, so stale or missing scrape data directly affects scale decisions.
3. If this target is down, your CPU/memory queries may return empty results and scaling logic can fail.

**Quick validation after starting Prometheus:**

```bash
# 1) Check Prometheus sees the node target as UP
curl -sG --data-urlencode 'query=up{job="node"}' http://localhost:9090/api/v1/query | python3 -m json.tool

# 2) Confirm a Node Exporter metric is being scraped
curl -s 'http://localhost:9090/api/v1/query?query=node_cpu_seconds_total' | python3 -m json.tool
```

Expected behavior: the `up{job="node"}` query returns value `1`, which means Prometheus can scrape Node Exporter successfully.

**If your setup differs:**

1. If Node Exporter runs on another machine, replace `localhost` with that machine's IP or hostname.
2. If you need lighter load on low-resource VMs, increase `scrape_interval` to `15s` or `30s`.
3. If you need faster detection, reduce interval (for example `5s`) but expect more Prometheus overhead.

**Start Prometheus:**

```bash
cd /opt/prometheus && ./prometheus &
```

> Prometheus runs in the background. Press Enter to get your shell prompt back.

**Verify it works:**

```bash
# Prometheus web UI — should load in your VM's browser
curl -s http://localhost:9090/-/healthy
# Expected output: Prometheus Server is Healthy.

# Query a metric via the API
curl -s 'http://localhost:9090/api/v1/query?query=up' | python3 -m json.tool
# Expected: "value": [..., "1"] meaning the node target is UP
```

> You can also open `http://192.168.56.10:9090` in your host browser to use the Prometheus web UI.

---

### Step 4: Install & Configure Grafana

Grafana provides visual dashboards for real-time monitoring.

```bash
# Install prerequisites
sudo apt install -y apt-transport-https software-properties-common

# Add Grafana's apt repository
wget -q -O - https://apt.grafana.com/gpg.key | sudo apt-key add -
echo "deb https://apt.grafana.com stable main" | sudo tee /etc/apt/sources.list.d/grafana.list
sudo apt update && sudo apt install grafana -y

# Enable and start Grafana
sudo systemctl enable --now grafana-server
```


```bash
cd ~/IITJ_VCC_A3/grafana
sudo dpkg -i grafana_12.4.2_amd64.deb
sudo apt -f install -y
sudo systemctl enable --now grafana-server
```



**Verify it works:**

```bash
sudo systemctl start grafana-server
sudo systemctl status grafana-server   # should be "active (running)sudo journalctl -u grafana-server -n 50 --no-pager  #If it fails to start, check the logs:
```
![alt text](grafana1.png)

![alt text](grafana2.png)


![alt text](grafana3.png)
**Configure Grafana** (from your host browser):

1. Open `http://192.168.56.10:3000` — default login is `admin` / `admin` (you'll be prompted to change it).
2. **Add Prometheus as a data source:**
   - Go to ⚙️ **Configuration → Data Sources → Add data source**.
   - Select **Prometheus**.
   - Set URL to `http://localhost:9090`.
   - Click **Save & Test** — should show "Data source is working".
3. **Import the custom dashboard from this repo:**
   - Go to **+ → Import**.
   - Click **Upload JSON file** and select `monitoring/grafana-dashboard.json` from this repo.
   - Select the Prometheus data source you just added.
   - Click **Import**.
4. **Or import the community Node Exporter dashboard:**
   - Go to **+ → Import** → enter dashboard ID `1860` → **Load** → select Prometheus → **Import**.

The custom dashboard (`grafana-dashboard.json`) shows two panels:
- **CPU Usage %** — `100 - (avg(rate(node_cpu_seconds_total{mode="idle"}[2m])) * 100)`
- **Memory Usage %** — `(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100`

These are the exact same queries the auto-scale script uses, so what you see in Grafana matches what triggers scaling.




![alt text](grafana4.png)

---

### Step 5: Configure AWS Credentials & Resources ✅

All substeps completed successfully. Below is a full summary of everything that was done and the key values used.

---

#### ✅ 5a. IAM User Created

| Field | Value |
|---|---|
| **Username** | `hybrid-cloud-autoscaler` |
| **Policy Attached** | `AmazonEC2FullAccess` (directly) |
| **Access Key ID** | `AKIA3MYREF4BBRCQDNTC` |

> ⚠️ **Never commit your Secret Access Key to git.** Enter it directly via `aws configure` on the VM.

**Steps taken:**
1. AWS Console → IAM → Users → Add user → `hybrid-cloud-autoscaler`.
2. Attached policy **AmazonEC2FullAccess** directly.
3. Created access key and saved credentials securely.

---

#### ✅ 5b. Key Pair Created

| Field | Value |
|---|---|
| **Key Pair Name** | `mh-vm1` |
| **Format** | `.pem` |
| **Region** | `us-east-1` |

**Steps taken:**
1. EC2 Console → Key Pairs → Create Key Pair → `mh-vm1`, `.pem` format.
2. `.pem` file downloaded automatically. Move it to a safe location and set permissions:

```bash
mv mh-vm1.pem ~/.ssh/
chmod 400 ~/.ssh/mh-vm1.pem
```

---

#### ✅ 5b-ii. Place the `.pem` Key on mh-vm1

The `mh-vm1.pem` file is currently inside the repo at `autoscale/mh-vm1.pem`. Move it to the standard SSH directory on the VM:

```bash
# On mh-vm1 — move key out of the repo into ~/.ssh/
mkdir -p ~/.ssh
mv ~/IITJ_VCC_A3/autoscale/mh-vm1.pem ~/.ssh/mh-vm1.pem

# Set strict permissions (SSH will refuse the key otherwise)
chmod 400 ~/.ssh/mh-vm1.pem

# Verify
ls -la ~/.ssh/mh-vm1.pem
```

Expected output:
```
-r-------- 1 mh-vm1 mh-vm1 1674 Mar 28 18:00 /home/mh-vm1/.ssh/mh-vm1.pem
```

> **Why move it out of the repo?** `.pem` private keys must never be committed to git. Moving to `~/.ssh/` keeps it secure and outside version control.

To SSH into the EC2 instance after it launches:
```bash
ssh -i ~/.ssh/mh-vm1.pem ubuntu@<EC2_PUBLIC_IP>
```

---

#### ✅ 5c. Security Group Created

| Field | Value |
|---|---|
| **Security Group Name** | `hybrid-cloud-sg` |
| **Security Group ID** | `sg-0312567d5a5a9df6d` |
| **VPC** | `vpc-0a2263deb0f61b88b` |
| **Region** | `us-east-1` |

**Inbound Rules configured:**

| Type | Port | Source | Purpose |
|---|---|---|---|
| SSH | 22 | 0.0.0.0/0 | SSH access to EC2 |
| Custom TCP | 5000 | 0.0.0.0/0 | Flask app |
| Custom TCP | 9090 | 0.0.0.0/0 | Prometheus |

---

#### ✅ 5d. Ubuntu 22.04 AMI Found (us-east-1)

| Field | Value |
|---|---|
| **AMI ID** | `ami-00de3875b03809ec5` |
| **AMI Name** | `ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-20260320` |
| **Owner** | `099720109477` (Canonical) |
| **Region** | `us-east-1` |

---

#### ✅ 5e. AWS CLI Configuration on the VM

```bash
sudo apt install -y awscli
aws configure
```

![alt text](aws.png)

```
AWS Access Key ID:     AKIA3MYREF4BBRCQDNTC
AWS Secret Access Key: <enter your secret key — do NOT store in this file>
Default region name:   us-east-1
Default output format: json
```

**Verify AWS access:**

```bash
aws sts get-caller-identity
# Should print your account ID and IAM user ARN
```

> ⚠️ **If `aws configure` does not work** (hangs, no prompt, or `command not found`), write the credentials file directly:

```bash
# Install AWS CLI if missing
sudo apt update && sudo apt install -y awscli

# Write credentials directly
mkdir -p ~/.aws

cat > ~/.aws/credentials << 'EOF'
[default]
aws_access_key_id = AKIA3MYREF4BBRCQDNTC
aws_secret_access_key = <your-secret-key>
EOF

cat > ~/.aws/config << 'EOF'
[default]
region = us-east-1
output = json
EOF

# Verify
aws sts get-caller-identity
```

Expected output:
```json
{
    "UserId": "...",
    "Account": "...",
    "Arn": "arn:aws:iam::...:user/hybrid-cloud-autoscaler"
}
```

If this command succeeds, boto3 will find the credentials automatically and the monitor script will be able to launch EC2 instances.

---

#### ✅ 5f. Update `autoscale/config.py`

`autoscale/config.py` is the **single place** that controls all AWS settings. No other file needs to be changed for credentials or resource IDs.

**What each line controls:**

| Line | What it controls | Value set |
|---|---|---|
| `AWS_REGION` | Which AWS region to launch EC2 in | `us-east-1` |
| `AMI_ID` | OS image used for the EC2 instance | `ami-00de3875b03809ec5` (Ubuntu 22.04, us-east-1) |
| `INSTANCE_TYPE` | EC2 size (free-tier eligible) | `t2.micro` |
| `KEY_NAME` | EC2 key pair name for SSH access | `mh-vm1` |
| `SECURITY_GROUP` | Firewall rules allowing ports 22, 5000, 9090 | `sg-0312567d5a5a9df6d` |

**How to apply it on the VM (inside mh-vm1):**

**1. Pull latest from git** (recommended — already updated):
```bash
cd ~/IITJ_VCC_A3
git pull origin main
```

**2. Or open and verify manually:**
```bash
nano ~/IITJ_VCC_A3/autoscale/config.py
```
![alt text](nano.png)
Ensure it looks like this:
```python
"""Configuration for hybrid cloud auto-scaling."""

PROMETHEUS_URL = "http://localhost:9090/api/v1/query"
THRESHOLD = 75.0          # percentage — scale when CPU or RAM exceeds this
CHECK_INTERVAL = 30       # seconds between each Prometheus poll

AWS_REGION = "us-east-1"
AMI_ID = "ami-00de3875b03809ec5"         # Ubuntu 22.04 LTS (us-east-1)
INSTANCE_TYPE = "t2.micro"               # free-tier eligible
KEY_NAME = "mh-vm1"                      # EC2 key pair name
SECURITY_GROUP = "sg-0312567d5a5a9df6d"  # hybrid-cloud-sg

INSTANCE_NAME_TAG = "AutoScaled-from-LocalVM"
```

**3. Save and exit** (`Ctrl+O`, Enter, `Ctrl+X` in nano).

---

#### Summary of All Resource IDs

| Resource | Value |
|---|---|
| **AMI ID** | `ami-00de3875b03809ec5` |
| **Key Pair** | `mh-vm1` |
| **Security Group ID** | `sg-0312567d5a5a9df6d` |
| **Region** | `us-east-1` |
| **IAM User** | `hybrid-cloud-autoscaler` |
| **Access Key ID** | `AKIA3MYREF4BBRCQDNTC` |

---

### Step 6: Install Python Dependencies

```bash
cd ~/IITJ_VCC_A3

# Ubuntu 23.04+ / Python 3.12 may block global pip installs (PEP 668).
# Create and use a virtual environment instead.
# Install venv tooling first (fixes "ensurepip is not available" error)
sudo apt update
sudo apt install -y python3-venv python3-full

# If the command above cannot find python3-venv on your distro, use:
# sudo apt install -y python3.12-venv

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r autoscale/requirements.txt
```

This installs:
- `boto3` — AWS SDK for Python (used to launch EC2)
- `requests` — HTTP client (used to query Prometheus API)
- `flask` — lightweight web framework (used by the sample app)

If your shell shows `(.venv)` in the prompt, the environment is active.
If not active in a new terminal, run:

```bash
cd ~/IITJ_VCC_A3
source .venv/bin/activate
```

---

### Step 7: Run the Full System

You need **three terminal windows/tabs** inside the VM. Open each with `Ctrl+Alt+T` or use `tmux`.

#### Terminal 1 — Start the Flask app

```bash
cd ~/IITJ_VCC_A3
source .venv/bin/activate
python app/app.py
```

Expected output:

```
 * Running on http://0.0.0.0:5000
```

**Verify:** Open `http://192.168.56.10:5000` in your host browser — you should see `Running on Local VM`.

![alt text](localFlask.png)

#### Terminal 2 — Start the monitor script

```bash
cd ~/IITJ_VCC_A3
source .venv/bin/activate
python autoscale/monitor_and_scale.py
```

Expected output (repeated every 30 seconds):

```
Monitoring started...
CPU: 3.2% | Memory: 42.1%
CPU: 2.8% | Memory: 42.3%
```

The script will keep printing metrics until a threshold is breached.

#### Terminal 3 — Run the stress test

```bash
cd ~/IITJ_VCC_A3
chmod +x stress-test/load_test.sh
./stress-test/load_test.sh
```

This installs `stress` (if not already present) and runs **4 parallel CPU workers for 120 seconds**, which should push CPU usage well above 75% on a 2-core VM.

---

### Step 8: Observe the Auto-Scale Event

Within **30–60 seconds** of starting the stress test, you should see the monitor script output:

```
CPU: 96.4% | Memory: 45.2%
THRESHOLD EXCEEDED - Launching AWS EC2 instance...
Launched EC2 instance: i-0abcdef1234567890
Cloud burst complete. Traffic can now be routed to EC2.
```

**What happened:**
1. The `stress` command saturated the CPUs.
2. Prometheus scraped the high CPU metrics from Node Exporter.
3. `monitor_and_scale.py` detected CPU > 75% on its next 30-second check.
4. Boto3 called AWS `run_instances` with the UserData script.
5. AWS launched a `t2.micro` EC2 instance that auto-installs Flask and starts the app.

**Verify the EC2 instance:**

```bash
# From the VM (or any machine with AWS CLI configured)
aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=AutoScaled-from-LocalVM" \
  --query "Reservations[].Instances[].[InstanceId, State.Name, PublicIpAddress]" \
  --output table
```

Once the instance state is `running` and it has a public IP, open `http://<EC2_PUBLIC_IP>:5000` — you should see `Running on AWS Cloud - Auto-Scaled!`.

> **Note:** The EC2 UserData script takes 1–2 minutes to finish installing packages and starting Flask after the instance launches.

**Watch it in Grafana:**

Open `http://192.168.56.10:3000` and view the dashboard — you'll see the CPU spike during the stress test, the threshold line at 75%, and the moment scaling was triggered.

---

## How the Auto-Scale Script Works (Detailed)

The core logic is in `autoscale/monitor_and_scale.py`:

```

![alt text](newec2.png)
┌─────────────────────────────┐
│     Start monitoring loop   │
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│  Query Prometheus for CPU   │
│  and Memory via HTTP GET    │
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│  CPU > 75% OR Mem > 75%?    │──── No ──→ Sleep 30s → loop back
└──────────┬──────────────────┘
           │ Yes
           ▼
┌─────────────────────────────┐
│  Already scaled? (SCALED    │──── Yes ──→ Sleep 30s → loop back
│  flag is True?)             │
└──────────┬──────────────────┘
           │ No
           ▼
┌─────────────────────────────┐
│  Launch EC2 via Boto3       │
│  - AMI, instance type, SG   │
│  - UserData bootstraps Flask │
│  Set SCALED = True          │
└─────────────────────────────┘
```

**Key design decisions:**
- **One-shot scaling**: only one EC2 instance is ever launched (the `SCALED` flag prevents duplicates). This keeps things simple and avoids runaway costs.
- **No scale-down**: the script does not terminate the EC2 instance when load drops. You must manually terminate it in the AWS console or via CLI.
- **UserData bootstrap**: the EC2 instance is self-contained — it installs its own Python, Flask, and app without needing SSH access.

---

## Cleanup & Cost Control

**Important:** The EC2 instance launched by this script will incur AWS charges if left running. After your demo:

```bash
# Find the instance ID
aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=AutoScaled-from-LocalVM" \
  --query "Reservations[].Instances[].InstanceId" \
  --output text

# Terminate it
aws ec2 terminate-instances --instance-ids <INSTANCE_ID>
```

Or terminate from the **AWS EC2 Console → Instances → select → Instance State → Terminate**.

---

## Troubleshooting

| Problem | Cause | Fix |
|---|---|---|
| `curl localhost:9100/metrics` returns nothing | Node Exporter not running | `sudo systemctl restart node_exporter` and check `systemctl status` |
| Monitor prints `Monitor error: connection refused` | Prometheus not reachable | Verify Prometheus is running: `curl http://localhost:9090/-/healthy` |
| Monitor prints `Monitor error: Unable to locate credentials` | AWS CLI not configured on VM | Run `aws configure` on the VM and enter Access Key, Secret Key, region `us-east-1` |
| CPU stays below 75% during stress test | VM has too many cores | Increase `--cpu` count in `load_test.sh` or reduce VM CPU cores to 2 |
| `botocore.exceptions.NoCredentialsError` | AWS CLI not configured | Run `aws configure` and enter valid credentials |
| `botocore.exceptions.ClientError: InvalidAMIID` | Wrong AMI for your region | Look up the correct Ubuntu 22.04 AMI ID for your `AWS_REGION` |
| EC2 launches but port 5000 unreachable | Security group misconfigured | Ensure inbound TCP 5000 is allowed in your security group |
| EC2 launches but Flask not running | UserData script failed | SSH into the EC2 instance and check `/var/log/cloud-init-output.log` |
| Grafana shows no data | Data source misconfigured | Verify Prometheus URL is `http://localhost:9090` in Grafana data source settings |

---

## Configuration Reference

All tuneable parameters live in `autoscale/config.py`:

| Parameter | Default | Description |
|---|---|---|
| `PROMETHEUS_URL` | `http://localhost:9090/api/v1/query` | Prometheus query API endpoint |
| `THRESHOLD` | `75.0` | CPU/memory percentage that triggers scaling |
| `CHECK_INTERVAL` | `30` | Seconds between each monitoring check |
| `AWS_REGION` | `us-east-1` | AWS region for the EC2 instance |
| `AMI_ID` | `ami-00de3875b03809ec5` | Ubuntu 22.04 AMI ID (us-east-1) |
| `INSTANCE_TYPE` | `t2.micro` | EC2 instance type (free-tier eligible) |
| `KEY_NAME` | `mh-vm1` | EC2 key pair name |
| `SECURITY_GROUP` | `sg-0312567d5a5a9df6d` | EC2 security group ID |
| `INSTANCE_NAME_TAG` | `AutoScaled-from-LocalVM` | Name tag applied to the launched instance |

---

## Key Operational Flow (Summary)

1. Local VM runs **Flask app** (port 5000) + **Node Exporter** (port 9100) + **Prometheus** (port 9090) + **Grafana** (port 3000).
2. **Monitor script** polls Prometheus API every 30 seconds for CPU and memory utilization.
3. On threshold breach (>75 %), **Boto3** launches a tagged EC2 instance and deploys the Flask app via UserData.
4. The EC2 public IP can be added to DNS or a load balancer for hybrid traffic routing.
5. **Grafana** visualizes the real-time CPU/memory behavior and the scaling event.

This is a **cloud bursting pattern**: baseline workloads remain on-premises (local VM), overflow is handled elastically in AWS.

---

## Git Push Commands

```bash
git add .
git commit -m "Hybrid cloud auto-scaling: local VM to AWS"
git push origin main
```


## Live Service URLs

| Service | Live URL |
|---|---|
| Grafana | [http://192.168.56.10:3000](http://192.168.56.10:3000) |
| Prometheus | [http://192.168.56.10:9090](http://192.168.56.10:9090) |
| Flask App | [http://192.168.56.10:5000](http://192.168.56.10:5000) |
| Node Exporter | [http://192.168.56.10:9100/metrics](http://192.168.56.10:9100/metrics) |

## Node Exporter 
![alt text](image-11.png)
-----
## Prometheus
![alt text](image-1.png)

---
##Grafhana
![alt text](image.png)
