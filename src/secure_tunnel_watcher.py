import os
import shutil
import sys
import time
import json
import traceback
import threading
import subprocess
from urllib.parse import urlparse

from awsiot.greengrasscoreipc.clientv2 import GreengrassCoreIPCClientV2
import awsiot.greengrasscoreipc.client as client
from awsiot.greengrasscoreipc.model import (
    QOS,
    IoTCoreMessage,
)

LOCK_FILE_PATH = "/app/lock/"

def parse_http_proxy(http_proxy):

    http_proxy_content = {}

    if http_proxy != None: 
        try:
            # extract all http proxy information
            proxy = urlparse(http_proxy)
            if proxy.hostname != None and proxy.port != None:
                http_proxy_content = {
                    "http-proxy-host": proxy.hostname,
                    "http-proxy-port": str(proxy.port),
                }
                if proxy.username != None and proxy.password != None:
                    http_proxy_content['http-proxy-auth-method'] = "UserNameAndPassword"
                    http_proxy_content['http-proxy-username'] = proxy.username
                    http_proxy_content['http-proxy-password'] = proxy.password
                else:
                    http_proxy_content['http-proxy-auth-method'] = "None"
                
                http_proxy_content["http-proxy-enabled"] = True
            else:
                http_proxy_content["http-proxy-enabled"] = False
            
        except Exception as e:
            print('Not able to parse proxy config: {}'.format(http_proxy))
            print('error: {}'.format(e))
            http_proxy_content["http-proxy-enabled"] = False
            
    else:
        http_proxy_content["http-proxy-enabled"] = False

    return http_proxy_content


class StreamHandler(client.SubscribeToIoTCoreStreamHandler):
    def __init__(self):
        super().__init__()
        self.proc = None

    def on_stream_event(self, event: IoTCoreMessage) -> None:
        try:
            print("New tunnel event received...")
            message_string = str(event.message.payload, "utf-8")
            msg = json.loads(message_string)
        except:
            print("ERROR: invalid tunnel event payload:", event.message.payload, file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            return

        for required_fields in ("region", "services", "clientAccessToken"):
            if required_fields not in msg:
                print(f"ERROR: incomplete tunnel event: missing {required_fields}", file=sys.stderr)
                return

        try:
            new_environ = os.environ.copy()
            new_environ["AWSIOT_TUNNEL_ACCESS_TOKEN"] = msg["clientAccessToken"]
            new_environ["LOCK_FILE_PATH"] = LOCK_FILE_PATH

            config = "dummy_config.json"
            with open(config, "w") as f:
                # no need to fill in any values, the file only needs to exists and have all required keys
                f.write("""{
                    "endpoint": "not_needed_see_argv",
                    "cert": "not_needed_see_argv",
                    "key": "not_needed_see_argv",
                    "root-ca": "not_needed_see_argv",
                    "thing-name": "not_needed_see_argv"
                }""")

            http_proxy_config = "http-proxy-config.conf"
            http_proxy_content = parse_http_proxy(os.getenv('HTTP_PROXY', None))
            # save proxy configuration
            with open(http_proxy_config, "w") as f:
                json.dump(http_proxy_content, f)

            cmd = [
                "/app/aws-iot-device-client",
                "--enable-tunneling", "true",
                "--tunneling-region", msg["region"],
                "--tunneling-service", msg["services"][0],
                "--endpoint", f"data.tunneling.iot.{msg['region']}.amazonaws.com",
                "--tunneling-disable-notification",
                "--config-file", config,
                "--http-proxy-config", http_proxy_config,
                "--log-level", "DEBUG",
            ]

            if self.proc and not self.proc.poll():
                print("Terminating existing aws-iot-device-client...")
                self.proc.terminate()
                time.sleep(5)

            if os.path.exists(LOCK_FILE_PATH):
                shutil.rmtree(LOCK_FILE_PATH)
            os.makedirs(LOCK_FILE_PATH, exist_ok=True)

            print(f"Starting aws-iot-device-client...")
            print("    ", " ".join(cmd))

            self.proc = subprocess.Popen(cmd, env=new_environ, start_new_session=True, stderr=subprocess.STDOUT)
            threading.Thread(target=self.proc.wait).start() # reap the process once it exits
        except:
            print("ERROR: failed to configure and start aws-iot-device-client", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            return

    def on_stream_error(self, error: Exception) -> bool: # pragma: nocover
        print("ERROR:", error)
        return True  # Return True to close stream, False to keep stream open.

    def on_stream_closed(self) -> None: # pragma: nocover
        print("Stream closed.")


def init_watcher():
    print("Starting Greengrass Secure Tunneling notification watcher...")

    if 'AWS_IOT_THING_NAME' not in os.environ:
        print("ERROR: missing AWS_IOT_THING_NAME. Are you running as a GGv2 component?", file=sys.stderr)
        sys.exit(1)

    topic_name = f"$aws/things/{os.environ['AWS_IOT_THING_NAME']}/tunnels/notify"
    client = GreengrassCoreIPCClientV2()
    client.subscribe_to_iot_core(
        topic_name=topic_name, qos=QOS.AT_LEAST_ONCE,
        stream_handler=StreamHandler(),
    )
    print(f"Subscribed to {topic_name}. Waiting for notifications...")


if __name__ == "__main__": # pragma: nocover
    init_watcher()

    while True:
        time.sleep(30)
