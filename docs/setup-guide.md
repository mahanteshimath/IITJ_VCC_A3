# Setup Guide (Detailed)

This guide implements the hybrid cloud architecture where a local VM is monitored and an EC2 instance is launched automatically when CPU or memory crosses 75%.

## A. Local VM Setup

1. Create Ubuntu 22.04 VM in VirtualBox:
   - 2 CPU cores minimum
   - 2 GB RAM minimum
   - 20 GB disk minimum
   - Bridged network mode

2. Update and install tools:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip curl wget net-tools
```

## B. Monitoring Stack

### 1) Node Exporter

```bash
wget https://github.com/prometheus/node_exporter/releases/download/v1.7.0/node_exporter-1.7.0.linux-amd64.tar.gz
tar -xvf node_exporter-1.7.0.linux-amd64.tar.gz
sudo mv node_exporter-1.7.0.linux-amd64/node_exporter /usr/local/bin/
sudo useradd -rs /bin/false node_exporter
sudo cp monitoring/node_exporter.service /etc/systemd/system/node_exporter.service
sudo systemctl daemon-reload
sudo systemctl enable --now node_exporter
```

### 2) Prometheus

```bash
wget https://github.com/prometheus/prometheus/releases/download/v2.48.0/prometheus-2.48.0.linux-amd64.tar.gz
tar -xvf prometheus-2.48.0.linux-amd64.tar.gz
sudo mv prometheus-2.48.0.linux-amd64 /opt/prometheus
sudo cp monitoring/prometheus.yml /opt/prometheus/prometheus.yml
cd /opt/prometheus && ./prometheus &
```

### 3) Grafana

```bash
sudo apt install -y apt-transport-https software-properties-common
wget -q -O - https://apt.grafana.com/gpg.key | sudo apt-key add -
echo "deb https://apt.grafana.com stable main" | sudo tee /etc/apt/sources.list.d/grafana.list
sudo apt update && sudo apt install grafana -y
sudo systemctl enable --now grafana-server
```

Grafana UI:
1. Open http://<VM_IP>:3000
2. Add Prometheus data source at http://localhost:9090
3. Import dashboard ID 1860

## C. Auto-Scale Script

Install dependencies and configure AWS credentials:

```bash
pip3 install -r autoscale/requirements.txt
aws configure
```

Edit [autoscale/config.py](../autoscale/config.py):
- AWS_REGION
- AMI_ID
- KEY_NAME
- SECURITY_GROUP

Run:

```bash
python3 autoscale/monitor_and_scale.py
```

## D. Local App + Stress Test

Run app:

```bash
python3 app/app.py
```

Generate CPU load:

```bash
chmod +x stress-test/load_test.sh
./stress-test/load_test.sh
```

Expected result: monitor detects >75% utilization and launches one EC2 instance.

## AWS Pre-Requisites

1. IAM user with programmatic access and AmazonEC2FullAccess.
2. EC2 key pair (download .pem).
3. Security group with inbound ports 22, 5000, and 9090.
4. Ubuntu AMI ID for your selected region.
