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
   | Name | `mh-vm` |
   | Type / Version | Linux / Ubuntu (64-bit) |
   | CPUs | **3** (minimum — needed to generate meaningful CPU metrics) |
   | RAM | **3710 MB** (2 GB minimum) |
   | Disk | **25 GB** (dynamically allocated VDI) |


![alt text](image.png)


4. **Attach the ISO** to the VM's optical drive and boot it.
5. **Install Ubuntu** — follow the installer defaults; create a user (e.g., `ubuntu`).
6. **Configure Networking**:
   - Shut down the VM → Settings → Network → Adapter 1 → change **Attached to** from `NAT` to **Bridged Adapter**.
   - Select your host's active network adapter (Wi-Fi or Ethernet).
   - Boot the VM again.
7. **Verify networking** from inside the VM:

   ```bash
   ip addr show          # note the IP address (e.g., 192.168.1.105)
   ping -c 3 google.com  # confirm internet access
   ```
![alt text](image-1.png)
![alt text](image-2.png)
8. **Update the system and install base packages**:

   ```bash
   sudo apt update && sudo apt upgrade -y
   sudo apt install -y python3 python3-pip curl wget net-tools git stress
   ```
   ![alt text](image-3.png)
   ![alt text](image-4.png)

   ![alt text](image-5.png)

9. **Clone this repository** inside the VM:

   ```bash
   git clone https://github.com/mahanteshimath/IITJ_VCC_A3.git
   cd IITJ_VCC_A3
   ```
![alt text](image-6.png)
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

**Verify it works:**

```bash
# Check service status — should show "active (running)"
sudo systemctl status node_exporter

# Fetch a metric — should return text with lines like node_cpu_seconds_total
curl -s http://localhost:9100/metrics | head -20
```

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

**What the config does** (`monitoring/prometheus.yml`):

```yaml
global:
  scrape_interval: 10s        # collect metrics every 10 seconds

scrape_configs:
  - job_name: 'node'          # label for this scrape target
    static_configs:
      - targets: ['localhost:9100']   # Node Exporter endpoint
```

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

> You can also open `http://<VM_IP>:9090` in your host browser to use the Prometheus web UI.

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

**Verify it works:**

```bash
sudo systemctl status grafana-server   # should be "active (running)"
```

**Configure Grafana** (from your host browser):

1. Open `http://<VM_IP>:3000` — default login is `admin` / `admin` (you'll be prompted to change it).
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

---

### Step 5: Configure AWS Credentials & Resources

Before the auto-scale script can launch EC2 instances, you need to set up AWS resources.

#### 5a. Create an IAM User

1. Log in to **AWS Console → IAM → Users → Add user**.
2. Set user name (e.g., `hybrid-cloud-autoscaler`).
3. Attach the policy **AmazonEC2FullAccess** directly.
4. Create the user and **save the Access Key ID and Secret Access Key**.

#### 5b. Create a Key Pair

1. Go to **EC2 Console → Key Pairs → Create Key Pair**.
2. Name it (e.g., `hybrid-cloud-key`), select `.pem` format.
3. Download the `.pem` file and keep it safe.

#### 5c. Create a Security Group

1. Go to **EC2 Console → Security Groups → Create Security Group**.
2. Name it (e.g., `hybrid-cloud-sg`).
3. Add **inbound rules**:

   | Type | Port | Source | Purpose |
   |---|---|---|---|
   | SSH | 22 | Your IP / 0.0.0.0/0 | SSH access to EC2 |
   | Custom TCP | 5000 | 0.0.0.0/0 | Flask app |
   | Custom TCP | 9090 | Your IP | Prometheus (optional) |

4. **Copy the Security Group ID** (e.g., `sg-0abc1234def56789`).

#### 5d. Find Your Region's Ubuntu AMI

1. Go to **EC2 Console → AMIs → Public images**.
2. Search for `ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*` owned by `099720109477` (Canonical).
3. **Copy the AMI ID** for your region (e.g., `ami-0c55b159cbfafe1f0` for `ap-south-1`).

#### 5e. Install AWS CLI & Configure Credentials on the VM

```bash
# Install AWS CLI
sudo apt install -y awscli

# Configure credentials (enter Access Key, Secret Key, region, output format)
aws configure
```

When prompted:

```
AWS Access Key ID [None]: <YOUR_ACCESS_KEY>
AWS Secret Access Key [None]: <YOUR_SECRET_KEY>
Default region name [None]: ap-south-1
Default output format [None]: json
```

**Verify AWS access:**

```bash
aws sts get-caller-identity
# Should print your account ID and IAM user ARN
```

#### 5f. Update `autoscale/config.py`

Open the config file and replace the placeholder values:

```python
"""Configuration for hybrid cloud auto-scaling."""

PROMETHEUS_URL = "http://localhost:9090/api/v1/query"
THRESHOLD = 75.0          # percentage — scale when CPU or RAM exceeds this
CHECK_INTERVAL = 30       # seconds between each Prometheus poll

AWS_REGION = "ap-south-1"                # ← your AWS region
AMI_ID = "ami-0c55b159cbfafe1f0"         # ← Ubuntu 22.04 AMI for your region
INSTANCE_TYPE = "t2.micro"               # ← free-tier eligible
KEY_NAME = "your-key-pair"               # ← name of your EC2 key pair (Step 5b)
SECURITY_GROUP = "sg-xxxxxxxx"           # ← your security group ID (Step 5c)

INSTANCE_NAME_TAG = "AutoScaled-from-LocalVM"
```

**You must update these three values:**
- `AMI_ID` — the AMI from Step 5d
- `KEY_NAME` — the key pair name from Step 5b (just the name, not the `.pem` path)
- `SECURITY_GROUP` — the security group ID from Step 5c

---

### Step 6: Install Python Dependencies

```bash
cd ~/IITJ_VCC_A3
pip3 install -r autoscale/requirements.txt
```

This installs:
- `boto3` — AWS SDK for Python (used to launch EC2)
- `requests` — HTTP client (used to query Prometheus API)
- `flask` — lightweight web framework (used by the sample app)

---

### Step 7: Run the Full System

You need **three terminal windows/tabs** inside the VM. Open each with `Ctrl+Alt+T` or use `tmux`.

#### Terminal 1 — Start the Flask app

```bash
cd ~/IITJ_VCC_A3
python3 app/app.py
```

Expected output:

```
 * Running on http://0.0.0.0:5000
```

**Verify:** Open `http://<VM_IP>:5000` in your host browser — you should see `Running on Local VM`.

#### Terminal 2 — Start the monitor script

```bash
cd ~/IITJ_VCC_A3
python3 autoscale/monitor_and_scale.py
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

Open `http://<VM_IP>:3000` and view the dashboard — you'll see the CPU spike during the stress test, the threshold line at 75%, and the moment scaling was triggered.

---

## How the Auto-Scale Script Works (Detailed)

The core logic is in `autoscale/monitor_and_scale.py`:

```
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
| Monitor prints `Monitor error: ...` | Prometheus not reachable | Verify Prometheus is running: `curl http://localhost:9090/-/healthy` |
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
| `AWS_REGION` | `ap-south-1` | AWS region for the EC2 instance |
| `AMI_ID` | `ami-0c55b159cbfafe1f0` | Ubuntu AMI ID (region-specific — **must update**) |
| `INSTANCE_TYPE` | `t2.micro` | EC2 instance type (free-tier eligible) |
| `KEY_NAME` | `your-key-pair` | EC2 key pair name (**must update**) |
| `SECURITY_GROUP` | `sg-xxxxxxxx` | EC2 security group ID (**must update**) |
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
