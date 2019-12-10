import urllib
import ssl
import sys
import socket
import platform
import psutil
from uuid import getnode as get_mac
import datetime
import fcntl
import struct

class Gazoo():

    def __init__(self):
        self.__hostname = socket.gethostname()
        self.__ip_address = self.get_ip_address("eth0")
        self.__osname = platform.system()
        self.__osver = platform.release()
        self.__num_cpu = psutil.cpu_count()
        mem = psutil.virtual_memory()
        self.__total_mem = mem.total
        diskStats = psutil.disk_usage('/')
        self.__total_disk = diskStats.total
        self.__role = "Trading"
        self.__model = "Pi B"
        self.__logURL = "https://mosias:mosias98@dionysus.quantumconfigurations.com/dionysus/index.php?%s"

    def postStats(self):
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        mac = get_mac()
        bootTime = datetime.datetime.fromtimestamp(psutil.boot_time()).strftime("%Y-%m-%d %H:%M:%S")
        params = urllib.urlencode({'op': 'GAZOO', 'hostname': self.__hostname, 'ip_address': self.__ip_address, 'osname': self.__osname, 'osver': self.__osver, 'cpu_pct': psutil.cpu_percent(interval=1), 'mem_pct': mem.percent, 'disk_pct': disk.percent, 'boot_time': bootTime, 'mac': mac, 'role': self.__role, 'model': self.__model, 'num_cpu': self.__num_cpu, 'total_mem': self.__total_mem, 'total_disk': self.__total_disk})
        self.postRecord(params)

    def get_ip_address(self, ifname):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        return socket.inet_ntoa(fcntl.ioctl(
            s.fileno(),
            0x8915,  # SIOCGIFADDR
            struct.pack('256s', ifname[:15])
        )[20:24])  

    def postRecord(self, params):
        #try:
        #gcontext = ssl.SSLContext()
        gcontext = ssl._create_unverified_context()
        urlHand = urllib.urlopen(self.__logURL % params, context=gcontext)
        resp = urlHand.read()
        print ("Ran gazoo: %s" % (resp))
        #except:
        #    e = sys.exc_info()[0]
        #    print ("Exception: %s" % repr(e))
            #print urlHand.geturl()
            #print urlHand.read()

def main():

    gazoo = Gazoo()

    gazoo.postStats()

if __name__ == "__main__":
    main()
