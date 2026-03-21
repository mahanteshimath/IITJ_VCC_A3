# Hybrid Cloud Auto-Scale (Local VM to AWS)

## Architecture Design

The system works as a pipeline: a local Ubuntu VM runs your application and Node Exporter, Prometheus scrapes metrics every 10 seconds, and a Python monitor script polls Prometheus. When CPU or RAM crosses 75%, the script uses Boto3 to launch an EC2 instance and deploy your app automatically.

Generated chart: docs/hybrid_cloud_architecture.png

## Deliverable 1: Step-by-Step Implementation

### Part A: Create a Local VM in VirtualBox

1. Download and install VirtualBox and an Ubuntu 22.04 ISO.
2. Create a new VM with at least 2 CPU cores, 2 GB RAM, and 20 GB disk.
3. Install Ubuntu, then run:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip curl wget net-tools
```

4. Set the VM network adapter to Bridged Adapter so it gets a LAN IP accessible from your host.

### Part B: Install Prometheus + Node Exporter + Grafana

#### Node Exporter

```bash
wget https://github.com/prometheus/node_exporter/releases/download/v1.7.0/node_exporter-1.7.0.linux-amd64.tar.gz
tar -xvf node_exporter-1.7.0.linux-amd64.tar.gz
sudo mv node_exporter-1.7.0.linux-amd64/node_exporter /usr/local/bin/
sudo useradd -rs /bin/false node_exporter
```

Create /etc/systemd/system/node_exporter.service:

```ini
[Unit]
Description=Node Exporter
After=network.target

[Service]
User=node_exporter
Group=node_exporter
Type=simple
ExecStart=/usr/local/bin/node_exporter

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now node_exporter
```

#### Prometheus

```bash
wget https://github.com/prometheus/prometheus/releases/download/v2.48.0/prometheus-2.48.0.linux-amd64.tar.gz
tar -xvf prometheus-2.48.0.linux-amd64.tar.gz
sudo mv prometheus-2.48.0.linux-amd64 /opt/prometheus
```

Configure /opt/prometheus/prometheus.yml:

```yaml
global:
  scrape_interval: 10s

scrape_configs:
  - job_name: 'node'
    static_configs:
      - targets: ['localhost:9100']
```

Start Prometheus:

```bash
cd /opt/prometheus && ./prometheus &
```

#### Grafana

```bash
sudo apt install -y apt-transport-https software-properties-common
wget -q -O - https://apt.grafana.com/gpg.key | sudo apt-key add -
echo "deb https://apt.grafana.com stable main" | sudo tee /etc/apt/sources.list.d/grafana.list
sudo apt update && sudo apt install grafana -y
sudo systemctl enable --now grafana-server
```

In Grafana (http://<VM_IP>:3000):
1. Add Prometheus data source (URL: http://localhost:9090)
2. Import dashboard ID 1860 (Node Exporter Full)

### Part C: Resource Monitor + AWS Auto-Scale Script

Install dependencies:

```bash
pip3 install boto3 requests
aws configure
```

Run monitor script:

```bash
python3 autoscale/monitor_and_scale.py
```

Behavior:
1. Poll Prometheus every 30 seconds
2. Compute CPU and RAM utilization
3. If CPU or RAM > 75% and not yet scaled:
   - Launch one EC2 instance with Boto3
   - Deploy Flask app via EC2 UserData

### Part D: Deploy a Sample Application

Run local app:

```bash
python3 app/app.py
```

Stress test:

```bash
chmod +x stress-test/load_test.sh
./stress-test/load_test.sh
```

Within about 60 seconds, the monitor should detect high load and launch an EC2 instance.

## Deliverable 2: AWS Pre-Requisites

| Resource | Configuration |
|---|---|
| IAM User | Programmatic access with AmazonEC2FullAccess policy |
| Key Pair | Create in EC2 console and download .pem |
| Security Group | Allow inbound TCP 22 (SSH), 5000 (Flask), 9090 (Prometheus) |
| AMI | Ubuntu AMI for your region (ap-south-1 for Mumbai) |

## Deliverable 3: Repository Structure

```text
hybrid-cloud-autoscale/
├── README.md
├── app/
│   └── app.py
├── monitoring/
│   ├── prometheus.yml
│   ├── node_exporter.service
│   └── grafana-dashboard.json
├── autoscale/
│   ├── monitor_and_scale.py
│   ├── config.py
│   └── requirements.txt
├── docs/
│   ├── architecture-diagram.png
│   ├── hybrid_cloud_architecture.png
│   └── setup-guide.md
└── stress-test/
    └── load_test.sh
```

## Git Push Commands

```bash
git init && git add .
git commit -m "Hybrid cloud auto-scaling: local VM to AWS"
git remote add origin https://github.com/<your-username>/hybrid-cloud-autoscale.git
git push -u origin main
```

## Key Operational Flow

1. Local VM runs Flask + Node Exporter + Prometheus + Grafana.
2. Monitor script polls Prometheus API every 30 seconds.
3. On threshold breach (>75%), Boto3 launches tagged EC2 instance and deploys Flask app.
4. EC2 public IP can be added to DNS/load balancer for hybrid traffic routing.
5. Grafana visualizes real-time behavior and scaling lifecycle.

This is a cloud bursting pattern: baseline workloads remain on-premises, overflow is handled elastically in AWS.
