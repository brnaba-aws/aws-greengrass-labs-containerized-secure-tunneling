import json
import pytest
import awsiot.greengrasscoreipc.model as model

from src.secure_tunnel_watcher import init_watcher, StreamHandler, parse_http_proxy


def test_subscribe_to_core(mocker, monkeypatch):
    monkeypatch.setenv("AWS_IOT_THING_NAME", "TestDevice")
    ipc_connect = mocker.patch("awsiot.greengrasscoreipc.connect")

    init_watcher()

    ipc_connect.assert_called_once()

def test_non_gg_runtime():
    with pytest.raises(SystemExit) as pytest_wrapped_e:
        # missing AWS_IOT_THING_NAME environment variable
        init_watcher()
    assert pytest_wrapped_e.type == SystemExit
    assert pytest_wrapped_e.value.code == 1

def test_subscribe_topic_handler(mocker):
    popen = mocker.patch("subprocess.Popen")
    stream_handler = StreamHandler()

    event = model.IoTCoreMessage(
        message=model.MQTTMessage(
            topic_name="TestTopicName",
            payload=json.dumps({
                "clientAccessToken": "foobar",
                "region": "TEST-Region",
                "services": ["TEST-Service"],
            }).encode()
        )
    )

    mocker.patch("os.path.exists")
    mocker.patch("shutil.rmtree")
    mocker.patch("os.makedirs")

    stream_handler.on_stream_event(event)

    calls = popen.call_args_list
    assert len(calls) == 1
    cmd = calls[0][0]
    env = calls[0][1]["env"]

    assert cmd == ([
        "/app/aws-iot-device-client",
        "--enable-tunneling", "true",
        "--tunneling-region", "TEST-Region",
        "--tunneling-service", "TEST-Service",
        "--endpoint", "data.tunneling.iot.TEST-Region.amazonaws.com",
        "--tunneling-disable-notification",
        "--config-file", "dummy_config.json",
        "--http-proxy-config", "http-proxy-config.conf",
        "--log-level", "DEBUG"
    ],)
    assert "AWSIOT_TUNNEL_ACCESS_TOKEN" in env
    assert env["AWSIOT_TUNNEL_ACCESS_TOKEN"] == "foobar"

@pytest.mark.parametrize("payload", ["", b"", "foobar", b"foobar", "{"])
def test_error_payload_device_client(mocker, payload):
    popen = mocker.patch("subprocess.Popen")
    stream_handler = StreamHandler()

    event = model.IoTCoreMessage(
        message=model.MQTTMessage(
            topic_name="TestTopicName",
            payload=payload,
        )
    )

    try:
        stream_handler.on_stream_event(event)
    except:
        pytest.fail("should not have raised exception")

    popen.assert_not_called()

def test_missing_field_device_client(mocker):
    popen = mocker.patch("subprocess.Popen")
    stream_handler = StreamHandler()

    event = model.IoTCoreMessage(
        message=model.MQTTMessage(
            topic_name="TestTopicName",
            payload=b"""{
                "foo": "bar"
            }""",
        )
    )

    try:
        stream_handler.on_stream_event(event)
    except:
        pytest.fail("should not have raised exception")

    popen.assert_not_called()

def test_popen_error_device_client(mocker):
    popen = mocker.patch("subprocess.Popen", side_effect=Exception("mock exception"))
    stream_handler = StreamHandler()

    event = model.IoTCoreMessage(
        message=model.MQTTMessage(
            topic_name="TestTopicName",
            payload=b"""{
                "region": "unknown-region",
                "services": "some-service",
                "clientAccessToken": "abcd1234"
            }""",
        )
    )

    mocker.patch("os.path.exists")
    mocker.patch("shutil.rmtree")
    mocker.patch("os.makedirs")

    try:
        stream_handler.on_stream_event(event)
    except:
        pytest.fail("should not have raised exception")

    popen.assert_called_once()

def test_rotate_token(mocker):
    mocker.patch("time.sleep")
    popen = mocker.patch("subprocess.Popen", create=True)
    stream_handler = StreamHandler()

    event = model.IoTCoreMessage(
        message=model.MQTTMessage(
            topic_name="TestTopicName",
            payload=b"""{
                "region": "unknown-region",
                "services": "some-service",
                "clientAccessToken": "abcd1234"
            }""",
        )
    )

    mocker.patch("os.path.exists")
    mocker.patch("shutil.rmtree")
    mocker.patch("os.makedirs")

    stream_handler.on_stream_event(event)

    popen.assert_called_once()
    assert stream_handler.proc is not None

    stream_handler.proc.poll = mocker.MagicMock(return_value=False)
    stream_handler.proc.terminate = mocker.MagicMock()

    stream_handler.on_stream_event(event)

    assert popen.call_count == 2
    stream_handler.proc.poll.assert_called_once()
    stream_handler.proc.terminate.assert_called_once()


def assert_proxy(result, expected):
    assert result == expected

def test_parse_http_proxy():
    proxy_content = parse_http_proxy('http://username:password@10.11.12.13:8080')
    proxy_expected = {
                    "http-proxy-enabled": True,
                    "http-proxy-host": "10.11.12.13",
                    "http-proxy-port": "8080",
                    "http-proxy-auth-method": "UserNameAndPassword",
                    "http-proxy-username": "username",
                    "http-proxy-password": "password"
    }
    assert proxy_content == proxy_expected

    proxy_content = parse_http_proxy('http://username:@10.11.12.13:8080')
    proxy_expected = {
                    "http-proxy-enabled": True,
                    "http-proxy-host": "10.11.12.13",
                    "http-proxy-port": "8080",
                    "http-proxy-auth-method": "UserNameAndPassword",
                    "http-proxy-username": "username",
                    "http-proxy-password": ""
    }
    assert proxy_content == proxy_expected

    proxy_content = parse_http_proxy('http://@10.11.12.13:8080')
    proxy_expected = {
                    "http-proxy-enabled": True,
                    "http-proxy-host": "10.11.12.13",
                    "http-proxy-port": "8080",
                    "http-proxy-auth-method": "None"
    }
    assert proxy_content == proxy_expected

    proxy_content = parse_http_proxy('http://10.11.12.13:8080')
    proxy_expected = {
                    "http-proxy-enabled": True,
                    "http-proxy-host": "10.11.12.13",
                    "http-proxy-port": "8080",
                    "http-proxy-auth-method": "None"
    }
    assert proxy_content == proxy_expected

    proxy_content = parse_http_proxy('http://test:afefez10.11.12.13:8080')
    proxy_expected = {
                    "http-proxy-enabled": False
    }
    assert proxy_content == proxy_expected
