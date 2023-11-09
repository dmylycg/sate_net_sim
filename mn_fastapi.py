
import asyncio
import subprocess
import uvicorn
from fastapi import BackgroundTasks, FastAPI
from fastapi.responses import RedirectResponse

from mininet.net import Mininet
from mininet.node import Controller, OVSSwitch


TTYD_HOST = '192.168.1.194'
TTYD_PORT = '5005'

async def _ttyd_service():
    cmd = 'ttyd -p ' + TTYD_PORT + ' -a -W nsenter -n'
    process =  await asyncio.create_subprocess_exec(*cmd.split(), stdout=asyncio.subprocess.PIPE)
    stdout, _ = await process.communicate()
    return stdout.decode().strip()
# asyncio.run() cannot be called from a running event loop

def ttyd_service():
    cmd = 'ttyd -p ' + TTYD_PORT + ' -a -W nsenter -n'
    process = subprocess.Popen(cmd.split(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    # stdout, _ = process.communicate()
    # return stdout.decode().strip()



class Lab:
    instance = None

    def __new__(cls, *args, **kwargs):
        if not cls.instance:
            cls.instance = super().__new__(cls)
        return cls.instance

    def __init__(self, *args, **kwargs):
        if not hasattr(self, 'initialized'):
            self.initialized = True
            self.net = Mininet(*args, **kwargs)
            self.built = False
            self.background = False
    
    def start(self, hosts_num: int, users_num: int, gates_num: int):
        # if not hasattr(self, 'built') or not self.built:
        if not self.built:
            self.built = True
            self.build(hosts_num, users_num, gates_num)
            self.hosts_num = hosts_num
            self.users_num = users_num
            self.gates_num = gates_num
            ttyd_service()
            #

    def build(self, hosts_num: int, users_num: int, gates_num: int):
        net = self.net
        self.switches = [net.addSwitch('s%d' % n) for n in [1,2]]
        privateDirs = [('/var/log', '/tmp/%(name)s/var/log'),
                   ('/var/run', '/tmp/%(name)s/var/run'), 
                   '/var/mn'] # 挂载目录       
        self.hosts = [net.addHost('h%d' % n, 
                         privateDirs = privateDirs) 
            for n in range(1, hosts_num + 1)]
        self.users = [net.addHost('user%d' % n, 
                         privateDirs = privateDirs, 
                         ip = '10.0.0.%d/24' % (255 - n),
                         defaultRoute ='user%d-eth0' % n)
            for n in range(1, users_num + 1)]    
        self.gates = [net.addHost('gate%d' % n, 
                         ip = '10.1.1.%d/24' % (255 - n),
                         defaultRoute = 'gate%d-eth0' % n)
            for n in range(1, gates_num + 1)]
        
        for h in self.hosts:
            for s in self.switches:
                net.addLink(h, s)
            # 连接卫星/中转空间
            h.setIP(intf=h.intfs[1], 
                    ip='10.1.1.%d/24' % (self.hosts.index(h)+1))
            # eth0为默认设置 此处设置eth1
            h.cmd('sysctl -w net.ipv4.conf.all.proxy_arp=1')
            # 设置代答 以往在net.build()后

        # switches[0]连接用户 switches[1]连接网关
        for user in self.users:
            net.addLink(self.switches[0], user)
            # user.setDefaultRoute(user.defaultIntf())
            # defaultIntf()默认返回最小端口 但是此处设置路由不生效
            # user.cmd('sysctl -w net.ipv4.neigh.default.gc_stale_time=10')
        for gate in self.gates:
            net.addLink(self.switches[1], gate)
            # gate.cmd('sysctl -w net.ipv4.neigh.default.gc_stale_time=10')

        net.build()

        self.switches[0].start([])
        self.switches[1].start([])
        
    def stop(self):
        if self.built:
            self.net.stop()           
            self.built = False
            self.switches, self.hosts, self.users, self.gates = [], [], [], []
            self.net.switches, self.net.hosts, self.net.links = [], [], []
            self.hosts_num, self.users_num, self.gates_num = 0, 0, 0
            # last way: clear all
            # delattr(self, 'net')
            # delattr(self, 'initialized')
        else:
            pass    

    def mySwitch(self, timeout):
        from time import sleep 
        cmd = ['ovs-ofctl', 'add-flow', 's1', 'in_port=s1-eth1,actions=output:s1-eth2']
        flow = 'in_port={},hard_timeout={},actions=output:{}'
        sleep(1)
        print('start')
        # 等待网络初始化
        hosts_num = self.hosts_num
        gates_num = self.gates_num
        users_num = self.users_num
        net = self.net
        user_intfs = [net.switches[0].intfs[hosts_num + user] 
                      for user in range(1, users_num + 1)]
        # 获取交换机用户端口名
        # 形如 [<Intf s1-eth21>, <Intf s1-eth22>, <Intf s1-eth23>]
        user_ports = ",".join(str(hosts_num + i) 
                        for i in range(1, users_num + 1))
        # 获取交换机用户端口号
        # 形如 '21,22,23'
        gate_intfs = [net.switches[1].intfs[hosts_num + user] 
                for user in range(1, gates_num + 1)]
        gate_ports = ",".join(str(hosts_num + i) 
                        for i in range(1, gates_num + 1))


        while True:
            switch_in = net.switches[0]
            switch_out = net.switches[1]     
            for i in range( 1, hosts_num + 1 ):
                cmd[2] = switch_in
                cmd1 = cmd.copy()
                cmd2 = cmd.copy()
                for k in range( 1, users_num + 1 ):
                    flow1 = flow.format(hosts_num + k, timeout, i)
                    cmd1[3] = flow1
                    switch_in.cmd(cmd1)
                flow2 = flow.format( i, timeout, user_ports)
                cmd2[3] = flow2
                switch_in.cmd(cmd2)

                cmd[2] = switch_out
                cmd3 = cmd.copy()
                cmd4 = cmd.copy()
                for k in range( 1, gates_num + 1 ):
                    flow3 = flow.format(hosts_num + k, timeout, i)                
                    cmd3[3] = flow3
                    switch_in.cmd(cmd3)
                flow4 = flow.format( i, timeout, gate_ports) 
                cmd4[3] = flow4
                switch_in.cmd(cmd4)

                # myFlush(net)
                try:
                    for k in range( 0, users_num + 0 ):
                        net.hosts[hosts_num + k].cmd('ip neigh flush all', shell=True)
                    for k in range( 0, gates_num + 0 ):
                        net.hosts[hosts_num + users_num + k].cmd('ip neigh flush all', shell=True)
                except Exception as e:
                    print(e)

                sleep(timeout)

    def get_terminal(self) -> list[dict]:
        print(list(map(lambda x: x.__dict__, self.users)))
        users = list(map(lambda x: {'name': x.name, 'ip': x.IP()}, self.users))
        gates = list(map(lambda x: {'name': x.name, 'ip': x.IP()}, self.gates))
        return users + gates
    
    def get_ttyd(self, name: str) -> str:
        # if self.net.get(name): name不存在 会报错
        if not self.net.nameToNode.get(name, None):
            return None
        pid = self.net.nameToNode.get(name).pid
        # url = 'http://' + TTYD_HOST + ':' + str(TTYD_PORT) + '/?pid=' + str(pid)
        url = 'http://' + TTYD_HOST + ':' + str(TTYD_PORT) + '/?arg=-t&arg=' + str(pid)
        # start with 'ttyd -p 5005 -a -W nsenter -n'
        return url


app = FastAPI(
    title="mini",
    docs_url="/"
    )

@app.get("/start")
async def start(background_tasks: BackgroundTasks):
    lab = Lab(controller=Controller, 
            switch=OVSSwitch,
            waitConnected=True,
            ipBase='10.0.0.0/24')
    try:
        lab.start(20, 3, 3)
    except Exception as e:
        print(e)
    if not lab.background:
        background_tasks.add_task(lab.mySwitch(30))
        lab.background = True

    terminal = lab.get_terminal()
    return {'terminal': terminal}


@app.get("/stop")
async def stop():
    flag = Lab().stop()
    return {"flag": flag}


@app.get("/ttyd/{name}")
async def ttyd(name: str):
    url = Lab().get_ttyd(name)
    return RedirectResponse(url = url)
    

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0")

# http://192.168.1.194:8000/ttyd/user1