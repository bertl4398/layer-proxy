from charms.reactive import when, when_not, set_flag, set_state, when_file_changed
from charmhelpers.core.hookenv import status_set
from charmhelpers.core.host import service, service_running, service_available
from charmhelpers.core.templating import render
from charmhelpers.core.hookenv import open_port, config

import urllib.request
import os
import stat

import subprocess as sp


def proxy_storage():
    return str(config('proxy-storage'))


def proxy_honeypot():
    return str(config('proxy-honeypot'))


@when_not('proxy.installed')
def install_proxy():
    status_set("maintenance", "Installing InfluxDB")
    # wget https://dl.influxdata.com/influxdb/releases/influxdb_1.7.9_amd64.deb
    # sudo dpkg -i influxdb_1.7.9_amd64.deb
    influxdb_url = "https://dl.influxdata.com/influxdb/releases/influxdb_1.7.9_amd64.deb"
    urllib.request.urlretrieve(influxdb_url, "influxdb_1.7.9_amd64.deb")
    sp.check_call(["dpkg", "-i", "influxdb_1.7.9_amd64.deb"])
    
    status_set("maintenance", "Running InfluxDB service")
    if service_running("influxdb"):
        service("restart", "influxdb")
    else:
        service("start", "influxdb")
    
    status_set("maintenance", "Installing Kapacitor")
    # wget https://dl.influxdata.com/kapacitor/releases/kapacitor_1.5.3_amd64.deb
    # sudo dpkg -i kapacitor_1.5.3_amd64.deb
    kapacitor_url = "https://dl.influxdata.com/kapacitor/releases/kapacitor_1.5.3_amd64.deb"
    urllib.request.urlretrieve(kapacitor_url, "kapacitor_1.5.3_amd64.deb")
    sp.check_call(["dpkg", "-i", "kapacitor_1.5.3_amd64.deb"])
    
    if service_running("kapacitor"):
        service("restart", "kapacitor")
    else:
        service("start", "kapacitor")
    status_set("maintenance", "Running Kapacitor service")

    # Enable http alert
    render(source="http_alert.tick.j2",
    target="/tmp/http_alert.tick",
    perms=0o775,
    context={
        'redirect': '{{ index .Tags "ip.saddr" }}'
    })

    sp.check_call(["kapacitor", "define", "http_alert",
                   "-tick", "/tmp/http_alert.tick"])
    sp.check_call(["kapacitor", "enable", "http_alert"])               

    status_set("maintenance", "Installing Traefik")
    # Traefik
    traefik_url = "https://github.com/containous/traefik/releases/download/v1.7.19/traefik"
    traefik_bin = "/usr/local/bin/traefik"
    urllib.request.urlretrieve(traefik_url, traefik_bin)
    
    st = os.stat(traefik_bin)
    os.chmod(traefik_bin, st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    os.mkdir("/etc/traefik")
    render(source="traefik.toml.j2",
        target="/etc/traefik/traefik.toml",
        perms=0o775,
        context={
            "proxy_storage": proxy_storage()
        })

    render(source="traefik.service.j2",
        target="/lib/systemd/system/traefik.service",
        perms=0o775,
        context={})
    
    status_set("maintenance", "Running Traefik")
    service("enable", "traefik")
    service("start", "traefik")

    open_port(80)

    # ulogd2
    status_set("maintenance", "Restart ulogd2")
    
    render(source="ulogd.conf.j2",
        target="/etc/ulogd.conf",
        perms=0o600,
        context={})
    service("restart", "ulogd2")

    # Load iptables rules
    status_set("maintenance", "Configure iptables")
    render(source="iptables.save.j2",
    target="/etc/iptables.save",
    perms=0o775,
    context={})
    sp.check_call(["iptables-restore", "/etc/iptables.save"])

    # Install proxy-agentd
    sp.check_call(["influx", "-execute", "CREATE DATABASE loghttp"])
    proxy_agent_url = "https://github.com/bertl4398/proxy-agentd/releases/download/v0.1-alpha/proxy-agentd"
    proxy_agent_bin = "/usr/local/bin/proxy-agentd"
    urllib.request.urlretrieve(proxy_agent_url, proxy_agent_bin)
    
    st = os.stat(proxy_agent_bin)
    os.chmod(proxy_agent_bin, st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    
    render(source="proxy-agentd.service.j2",
        target="/lib/systemd/system/proxy-agentd.service",
        perms=0o775,
        context={})

    render(source="proxy_conf.json.j2",
        target="/etc/proxy_conf.json",
        perms=0o600,
        context={
            "proxy_honeypot": proxy_honeypot()
        })
    
    status_set("maintenance", "Running Proxy Agent")
    service("enable", "proxy-agentd")
    service("start", "proxy-agentd")

    status_set("active", "Proxy agent ready")
    set_state('proxy.installed')


@when_file_changed('/lib/systemd/system/traefik.service')
def restart():
    open_port(80)
    if service_running("traefik"):
        service("restart", "traefik")
    else:
        service("start", "traefik")
    status_set("active", "")