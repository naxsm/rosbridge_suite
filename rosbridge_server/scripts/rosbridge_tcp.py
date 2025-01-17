#!/usr/bin/env python

# from rospy import init_node, get_param, loginfo, on_shutdown, Publisher
from functools import partial
from signal import SIG_DFL, SIGINT, signal
from threading import Thread

import rclpy
from rclpy.node import Node

#from rclpy.qos import QoSDurabilityPolicy, QoSProfile
from rclpy.qos import DurabilityPolicy, QoSProfile
from rosbridge_library.capabilities.advertise import Advertise
from rosbridge_library.capabilities.advertise_service import AdvertiseService
from rosbridge_library.capabilities.call_service import CallService
from rosbridge_library.capabilities.publish import Publish
from rosbridge_library.capabilities.subscribe import Subscribe
from rosbridge_library.capabilities.unadvertise_service import UnadvertiseService
from std_msgs.msg import Int32

from rosbridge_server import RosbridgeTcpSocket

try:
    import SocketServer
except ImportError:
    import socketserver as SocketServer

import sys
import threading
import time
import traceback

#TODO: take care of socket timeouts and make sure to close sockets after killing program to release network ports

#TODO: add new parameters to websocket version! those of rosbridge_tcp.py might not be needed, but the others should work well when adding them to .._websocket.py

# update  reference https://docs.ros.org/en/foxy/Contributing/Migration-Guide-Python.html
# update to a class and could be compile to a excutable file
def shutdown_hook(server):
        server.shutdown()

class RosbridgeTcpsocketNode(Node):
    def __init__(self):
        super().__init__('rosbridge_tcp')

        """
        Parameter handling:
         - try to get parameter from parameter server (..define those via launch-file)
         - overwrite value if given as commandline-parameter

        BEGIN...
        """

        #TODO: ensure types get cast correctly after getting from parameter server
        #TODO: check if ROS parameter server uses None string for 'None-value' or Null or something else, then change code accordingly

        # update parameters from parameter server or use default value ( second parameter of get_param )
        # port = get_param('~port', 9090)
        port = self.declare_parameter('port', 9090).value
        self._port = port
        # host = get_param('~host', '')
        host = self.declare_parameter('host', '127.0.0.1').value
        self._host = host

        RosbridgeTcpSocket.ros_node = self
        # incoming_buffer = get_param('~incoming_buffer', RosbridgeTcpSocket.incoming_buffer)
        incoming_buffer = self.declare_parameter('incoming_buffer', RosbridgeTcpSocket.incoming_buffer).value
        # socket_timeout = get_param('~socket_timeout', RosbridgeTcpSocket.socket_timeout)
        socket_timeout = self.declare_parameter('socket_timeout', RosbridgeTcpSocket.socket_timeout).value
        # retry_startup_delay = get_param('~retry_startup_delay', 5.0)  # seconds
        retry_startup_delay = self.declare_parameter('retry_startup_delay', 5.0).value  # seconds
        # fragment_timeout = get_param('~fragment_timeout', RosbridgeTcpSocket.fragment_timeout)
        fragment_timeout = self.declare_parameter('fragment_timeout', RosbridgeTcpSocket.fragment_timeout).value
        # delay_between_messages = get_param('~delay_between_messages', RosbridgeTcpSocket.delay_between_messages)
        delay_between_messages = self.declare_parameter('delay_between_messages', RosbridgeTcpSocket.delay_between_messages).value
        self._delay_between_messages = delay_between_messages
        # max_message_size = get_param('~max_message_size', RosbridgeTcpSocket.max_message_size)
        max_message_size = self.declare_parameter('max_message_size', RosbridgeTcpSocket.max_message_size).value
        # unregister_timeout = get_param('~unregister_timeout', RosbridgeTcpSocket.unregister_timeout)
        unregister_timeout = self.declare_parameter('unregister_timeout', RosbridgeTcpSocket.unregister_timeout).value
        # bson_only_mode = get_param('~bson_only_mode', False)
        bson_only_mode = self.declare_parameter('bson_only_mode', RosbridgeTcpSocket.bson_only_mode).value
        #bson_only_mode = True # override
        print('bson_only_mode:' + str(bson_only_mode))
        
        if max_message_size == "None":
            max_message_size = None

        # Get the glob strings and parse them as arrays.
        RosbridgeTcpSocket.topics_glob = [
                element.strip().strip("'")
                # for element in get_param('~topics_glob', '')[1:-1].split(',')
                for element in self.declare_parameter('topics_glob', '').value[1:-1].split(',')
                if len(element.strip().strip("'")) > 0]
        RosbridgeTcpSocket.services_glob = [
                element.strip().strip("'")
                # for element in get_param('~services_glob', '')[1:-1].split(',')
                for element in self.declare_parameter('services_glob', '').value[1:-1].split(',')
                if len(element.strip().strip("'")) > 0]
        RosbridgeTcpSocket.params_glob = [
                element.strip().strip("'")
                # for element in get_param('~params_glob', '')[1:-1].split(',')
                for element in self.declare_parameter('params_glob', '').value[1:-1].split(',')
                if len(element.strip().strip("'")) > 0]
        
        # Publisher for number of connected clients
        # RosbridgeTcpSocket.client_count_pub = Publisher('client_count', Int32, queue_size=10, latch=True)
        # Publisher for number of connected clients
        # QoS profile with transient local durability (latched topic in ROS 1).
        client_count_qos_profile = QoSProfile(
            depth=1,
            #durability=QoSDurabilityPolicy.RMW_QOS_POLICY_DURABILITY_TRANSIENT_LOCAL
            #durability=DurabilityPolicy.VOLATILE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        RosbridgeTcpSocket.client_count_pub = self.create_publisher(Int32, 'client_count', qos_profile=client_count_qos_profile)
        # RosbridgeTcpSocket.client_count_pub.publish(0)
        RosbridgeTcpSocket.client_count_pub.publish(Int32(data=0))

        # update parameters if provided via commandline
        # .. could implemented 'better' (value/type checking, etc.. )
        if "--port" in sys.argv:
            idx = sys.argv.index("--port") + 1
            if idx < len(sys.argv):
                port = int(sys.argv[idx])
            else:
                print("--port argument provided without a value.")
                sys.exit(-1)

        if "--host" in sys.argv:
            idx = sys.argv.index("--host") + 1
            if idx < len(sys.argv):
                host = str(sys.argv[idx])
            else:
                print("--host argument provided without a value.")
                sys.exit(-1)

        if "--incoming_buffer" in sys.argv:
            idx = sys.argv.index("--incoming_buffer") + 1
            if idx < len(sys.argv):
                incoming_buffer = int(sys.argv[idx])
            else:
                print("--incoming_buffer argument provided without a value.")
                sys.exit(-1)

        if "--socket_timeout" in sys.argv:
            idx = sys.argv.index("--socket_timeout") + 1
            if idx < len(sys.argv):
                socket_timeout = int(sys.argv[idx])
            else:
                print("--socket_timeout argument provided without a value.")
                sys.exit(-1)

        if "--retry_startup_delay" in sys.argv:
            idx = sys.argv.index("--retry_startup_delay") + 1
            if idx < len(sys.argv):
                retry_startup_delay = int(sys.argv[idx])
            else:
                print("--retry_startup_delay argument provided without a value.")
                sys.exit(-1)

        if "--fragment_timeout" in sys.argv:
            idx = sys.argv.index("--fragment_timeout") + 1
            if idx < len(sys.argv):
                fragment_timeout = int(sys.argv[idx])
            else:
                print("--fragment_timeout argument provided without a value.")
                sys.exit(-1)

        if "--delay_between_messages" in sys.argv:
            idx = sys.argv.index("--delay_between_messages") + 1
            if idx < len(sys.argv):
                delay_between_messages = float(sys.argv[idx])
            else:
                print("--delay_between_messages argument provided without a value.")
                sys.exit(-1)

        if "--max_message_size" in sys.argv:
            idx = sys.argv.index("--max_message_size") + 1
            if idx < len(sys.argv):
                value = sys.argv[idx]
                if value == "None":
                    max_message_size = None
                else:
                    max_message_size = int(value)
            else:
                print("--max_message_size argument provided without a value. (can be None or <Integer>)")
                sys.exit(-1)

        if "--unregister_timeout" in sys.argv:
            idx = sys.argv.index("--unregister_timeout") + 1
            if idx < len(sys.argv):
                unregister_timeout = float(sys.argv[idx])
            else:
                print("--unregister_timeout argument provided without a value.")
                sys.exit(-1)

        # export parameters to handler class
        RosbridgeTcpSocket.incoming_buffer = incoming_buffer
        RosbridgeTcpSocket.socket_timeout = socket_timeout
        RosbridgeTcpSocket.fragment_timeout = fragment_timeout
        RosbridgeTcpSocket.delay_between_messages = delay_between_messages
        RosbridgeTcpSocket.max_message_size = max_message_size
        RosbridgeTcpSocket.unregister_timeout = unregister_timeout
        RosbridgeTcpSocket.bson_only_mode = bson_only_mode

        if "--topics_glob" in sys.argv:
            idx = sys.argv.index("--topics_glob") + 1
            if idx < len(sys.argv):
                value = sys.argv[idx]
                if value == "None":
                    RosbridgeTcpSocket.topics_glob = []
                else:
                    RosbridgeTcpSocket.topics_glob = [element.strip().strip("'") for element in value[1:-1].split(',')]
            else:
                print("--topics_glob argument provided without a value. (can be None or a list)")
                sys.exit(-1)

        if "--services_glob" in sys.argv:
            idx = sys.argv.index("--services_glob") + 1
            if idx < len(sys.argv):
                value = sys.argv[idx]
                if value == "None":
                    RosbridgeTcpSocket.services_glob = []
                else:
                    RosbridgeTcpSocket.services_glob = [element.strip().strip("'") for element in value[1:-1].split(',')]
            else:
                print("--services_glob argument provided without a value. (can be None or a list)")
                sys.exit(-1)

        if "--params_glob" in sys.argv:
            idx = sys.argv.index("--params_glob") + 1
            if idx < len(sys.argv):
                value = sys.argv[idx]
                if value == "None":
                    RosbridgeTcpSocket.params_glob = []
                else:
                    RosbridgeTcpSocket.params_glob = [element.strip().strip("'") for element in value[1:-1].split(',')]
            else:
                print("--params_glob argument provided without a value. (can be None or a list)")
                sys.exit(-1)

        if "--bson_only_mode" in sys.argv:
            bson_only_mode = True

        # To be able to access the list of topics and services, you must be able to access the rosapi services.
        if RosbridgeTcpSocket.services_glob:
            RosbridgeTcpSocket.services_glob.append("/rosapi/*")

        Subscribe.topics_glob = RosbridgeTcpSocket.topics_glob
        Advertise.topics_glob = RosbridgeTcpSocket.topics_glob
        Publish.topics_glob = RosbridgeTcpSocket.topics_glob
        AdvertiseService.services_glob = RosbridgeTcpSocket.services_glob
        UnadvertiseService.services_glob = RosbridgeTcpSocket.services_glob
        CallService.services_glob = RosbridgeTcpSocket.services_glob

        """
        ...END (parameter handling)
        """

class TCPThread(Thread):
    def __init__(self, host, port):
        super().__init__()
        self.host = host
        self.port = port

    def run(self):
        with SocketServer.ThreadingTCPServer((self.host, self.port), RosbridgeTcpSocket) as server:
            try:
                print("serving forever")
                server.serve_forever()
            finally:
                print("finished serving, close")
                server.server_close()


# if __name__ == "__main__":
def main(args=None):
    if args is None:
        args = sys.argv

    loaded = False
    retry_count = 0
    rclpy.init(args=args)
    print("rclpy init args: " + str(args))
    rosbridge_tcpsocket_node = RosbridgeTcpsocketNode()
    # while not loaded:
    #     retry_count += 1
    #     print("trying to start rosbridge TCP server..")
    try:
        print("")
        # update to ros2
        # rclpy.init(args=sys.argv)
        # node = rclpy.create_node('rosbridge_tcp')

        # init_node("rosbridge_tcp")
        signal(SIGINT, SIG_DFL)

        # Server host is a tuple ('host', port)
        # empty string for host makes server listen on all available interfaces
        SocketServer.ThreadingTCPServer.allow_reuse_address = True
        host = rosbridge_tcpsocket_node._host
        port = rosbridge_tcpsocket_node._port

        tcp_thread = TCPThread(host, port)
        tcp_thread.start()
        rosbridge_tcpsocket_node.get_logger().info("Rosbridge TCP server started on port " + str(port))

        loaded = True

        tnat = rosbridge_tcpsocket_node.get_topic_names_and_types()
        print("bs, tnat=" + str(tnat))
        for tn, _ in tnat:
            print(tn + " subs:" + str(rosbridge_tcpsocket_node.get_subscriptions_info_by_topic(tn)))
            print(tn + " pubs:" + str(rosbridge_tcpsocket_node.get_publishers_info_by_topic(tn)))

        print("rclpy spinning!")

        #import time
        #time.sleep(3.33)
        while True:
            try:
                #rclpy.spin(rosbridge_tcpsocket_node)
                rclpy.spin_once(rosbridge_tcpsocket_node, timeout_sec=0.3)
                #print('spun once...')
            except:
                print('exc in spin')
                print(sys.exc_info())
                import traceback; traceback.print_exc()

        print("rclpy done spinning!")

        return
        with SocketServer.TCPServer((host, port), RosbridgeTcpSocket) as server:
        # server = SocketServer.ThreadingTCPServer((host, port), RosbridgeTcpSocket)
        # server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        # server_thread.start()
        # on_shutdown(partial(shutdown_hook, server))
        # 也许再也不需要使用hook_shutdown 参见：https://github.com/ros2/rclpy/issues/244
        # rclpy.context.Context.on_shutdown(partial(shutdown_hook, server))

        # loginfo("Rosbridge TCP server started on port %d", port)
            server_thread = threading.Thread(target=server.serve_forever)
            server_thread.start()
            rosbridge_tcpsocket_node.get_logger().info("Rosbridge TCP server started on port " + str(port))

            loaded = True


            rclpy.spin(rosbridge_tcpsocket_node)
            # print('serving forever')
            # server.serve_forever()
            # print('served forever')
    except Exception as e:
        time.sleep(rosbridge_tcpsocket_node._delay_between_messages)
        print("server not loaded"+e.args)
        print(traceback.format_exc())


if __name__ == '__main__':
    main()
