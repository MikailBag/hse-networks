import subprocess
import os
import sys
import time

# vyos 5 (апстрим-маршрутизатор, 10.1.0.1/16)
CONFIG_UPSTREAM = [
    # Настраиваем интерфейс для нашего маршрутизатора
    "set interfaces ethernet eth0 address 10.1.0.1/16",
]

# Настраивает DHCP для подсети 10.0.${byte}.0/24
def make_dhcp_subnet_config(byte):
    return [
        f"set service dhcp-server shared-network-name 'LAN{byte}' authoritative",
        f"set service dhcp-server shared-network-name 'LAN{byte}' subnet 10.0.{byte}.0/24 default-router 10.0.{byte}.1",
        # Для DNS сделаем вид, что в eve-ng есть интернет и доступен cloudflare dns
        f"set service dhcp-server shared-network-name 'LAN{byte}' subnet 10.0.{byte}.0/24 name-server 1.1.1.1",
        f"set service dhcp-server shared-network-name 'LAN{byte}' subnet 10.0.{byte}.0/24 range 0 start 10.0.{byte}.11",
        f"set service dhcp-server shared-network-name 'LAN{byte}' subnet 10.0.{byte}.0/24 range 0 stop 10.0.{byte}.254",
    ]

# наш маршрутизатор, отвечает за 10.0.0.0/16
CONFIG_ROUTER = [
    # Настраиваем интерфейс для связи с апстримом
    "set interfaces ethernet eth1 address 10.1.0.100/16",
    # Настраиваем vlan 10 как подсеть 10.0.10.0/24
    "set interfaces ethernet eth0 vif 10 address 10.0.10.1/24",
    # Настраиваем vlan 20 как подсеть 10.0.20.0/24
    "set interfaces ethernet eth0 vif 20 address '10.0.20.1/24'",
    # Настраиваем source NAT
    # Обрабатываем трафик, улетающий в апстрим
    "set nat source rule 50 outbound-interface eth1",
    # Давайте выберем для адресов NAT пул 10.1.0.0/15
    # Благодаря такому пулу можно не настраивать смену портов
    "set nat source rule 50 translation address masquerade"
] + make_dhcp_subnet_config('10') + make_dhcp_subnet_config('20')

# настраивает интерфейс на распределяющем свитче в сторону свитча для подсети
def configure_interface_from_agg_to_access(iface):
    return [
        f"set interfaces bridge br0 member interface {iface}",
        # ставим высокий приоритет, так как все наши линки должны быть основными
        f"set interfaces bridge br0 member interface {iface} priority 10"
    ]

# распределяющий свитч
CONFIG_AGG_SWITCH = [
    # Настраиваем интерфейсы, между которыми надо коммутировать пакеты
    # Интерфейс в сторону маршрутизатора
    "set interfaces bridge br0 member interface eth0",
    # Включаем stp
    "set interfaces bridge br0 stp"
] + configure_interface_from_agg_to_access("eth1") + configure_interface_from_agg_to_access("eth2")

# настраивает интерфейс в сторону клиента
def configure_client_interface(vlan, iface):
    return [        
        # TODO: есть ли способ делать это для сразу для всех интерфейсов кроме eth1/eth2, чтобы упростить подключение нескольких клиентов?
        f"set interfaces bridge br0 member interface {iface} native-vlan {vlan}"
    ]

# свитч для подсети, общая часть
CONFIG_ACCESS_SWITCH_COMMON = [
    # Включаем VLAN-aware bridging
    "set interfaces bridge br0 enable-vlan",
    # Настраиваем интерфейсы в сторону других свитчей
    # eth1: тут мы стыкуемся с другим свитчем уровня доступа, поэтому разрешаем все релевантные vlan-ы,
    # но зарезаем приоритет (в итоге этот интерфейс блокируется STP)
    "set interfaces bridge br0 member interface eth1 allowed-vlan 1-25",
    "set interfaces bridge br0 member interface eth1 priority 1",
    # eth2: тут мы стыкуемся с распределяющем свитчем, поэтому не только разрешаем вланы, но и повышаем приоритет
    "set interfaces bridge br0 member interface eth2 allowed-vlan 1-25",
    "set interfaces bridge br0 member interface eth2 priority 10",
    # Тут тоже включаем STP
    "set interfaces bridge br0 stp"
]

# теперь можем сгенерировать конфиги свитчей
CONFIG_ACC_SWITCH_1 = CONFIG_ACCESS_SWITCH_COMMON + configure_client_interface("10", "eth0")
CONFIG_ACC_SWITCH_2 = CONFIG_ACCESS_SWITCH_COMMON + configure_client_interface("20", "eth0")

# Конфиг для клиентов, тут все должно работать автомагически
CONFIG_CLIENT = [
    "ip dhcp"
]


DEVICES = {
    'upstream': {
        'port': 32774,
        'config': CONFIG_UPSTREAM
    },
    'router': {
        'port': 32770,
        'config': CONFIG_ROUTER
    },
    'agg': {
        'port': 32771,
        'config': CONFIG_AGG_SWITCH
    },
    'acc1': {
        'port': 32772,
        'config': CONFIG_ACC_SWITCH_1
    },
    'acc2': {
        'port': 32773,
        'config': CONFIG_ACC_SWITCH_2
    },
    'vpcs1': {
        'port': 32775,
        'config': CONFIG_CLIENT
    },
    'vpcs2': {
        'port': 32776,
        'config': CONFIG_CLIENT
    }
}

# Из-за особенностей локального сетапа ходить на узлы приходится через ssh-туннель
JUMP_USERNAME = 'mb'
JUMP_HOST = '192.168.1.10'
VM_IP = "192.168.184.128"

def run_tunnel():
    cmd = ['ssh', f"{JUMP_USERNAME}@{JUMP_HOST}"]
    for device in DEVICES.values():
        port = device['port']
        cmd += ['-L', f"127.0.0.1:{port}:{VM_IP}:{port}"]
    cmd += ['-L', f"127.0.0.1:8000:{VM_IP}:80"]
    print("will execute", cmd)
    os.execvp(cmd[0], cmd)
    


def configure_device(device_name):
    conf = DEVICES[device_name]
    print(f"--- Configuring {device_name} ({conf['port']}) ---")
    commands = []
    if not 'vpcs' in device_name: 
        commands = ['vyos', 'vyos']
        commands += ['configure', 'load']
    commands += conf['config']
    if not 'vpcs' in device_name:
        commands += ['commit', 'save', 'exit']
        commands += ['exit', chr(29), "quit"] 
    commands += [chr(29), 'quit']
    p = subprocess.Popen(['telnet', '127.0.0.1', str(conf['port'])], stdin=subprocess.PIPE, stdout=sys.stdout, stderr=sys.stderr)
    time.sleep(2.0)
    for cmd in commands:
        # print(f"> {cmd}")
        cmd = cmd + "\n"
        p.stdin.write(cmd.encode())
        p.stdin.flush()
        time.sleep(3.0)
        if 'ip dhcp' in cmd:
            time.sleep(15.0)
    p.communicate(timeout=3.0)
    assert p.returncode == 0





def main():
    objects = sys.argv[1:]
    if 'tunnel' in objects:
        assert len(objects) == 1
        run_tunnel()
    for device in objects:
        configure_device(device)

if __name__ == '__main__':
    main()
