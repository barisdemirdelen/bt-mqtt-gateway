import time

from mqtt import MqttMessage

from workers.base import BaseWorker
import logger

REQUIREMENTS = ["bluepy"]
_LOGGER = logger.get(__name__)


class ToothbrushWorker(BaseWorker):
    def __init__(self, command_timeout, global_topic_prefix, **kwargs):
        self.devices = None
        self.retain = True
        super().__init__(command_timeout, global_topic_prefix, **kwargs)

    def searchmac(self, devices, mac):
        for dev in devices:
            if dev.addr == mac.lower():
                return dev

        return None

    def status_update(self):
        from bluepy.btle import Scanner, DefaultDelegate

        class ScanDelegate(DefaultDelegate):
            def __init__(self):
                DefaultDelegate.__init__(self)

            def handleDiscovery(self, dev, isNewDev, isNewData):
                if isNewDev:
                    _LOGGER.debug("Discovered new device: %s" % dev.addr)

        scanner = Scanner().withDelegate(ScanDelegate())
        devices = scanner.scan(5.0)
        ret = []

        for name, mac in self.devices.items():
            device = self.searchmac(devices, mac)
            if device is None:
                ret.append(
                    MqttMessage(
                        topic=self.format_topic(name + "/presence"),
                        payload="0",
                        retain=self.retain,
                    )
                )
            else:
                ret.append(
                    MqttMessage(
                        topic=self.format_topic(name + "/presence/rssi"),
                        payload=device.rssi,
                        retain=self.retain,
                    )
                )
                ret.append(
                    MqttMessage(
                        topic=self.format_topic(name + "/presence"),
                        payload="1",
                        retain=self.retain,
                    )
                )
                _LOGGER.debug("text: %s" % device.getValueText(255))
                bytes_ = bytearray(bytes.fromhex(device.getValueText(255)))
                ret.append(
                    MqttMessage(
                        topic=self.format_topic(name + "/running"),
                        payload=bytes_[5],
                        retain=self.retain,
                    )
                )
                ret.append(
                    MqttMessage(
                        topic=self.format_topic(name + "/pressure"),
                        payload=bytes_[6],
                        retain=self.retain,
                    )
                )
                ret.append(
                    MqttMessage(
                        topic=self.format_topic(name + "/time"),
                        payload=bytes_[7] * 60 + bytes_[8],
                        retain=self.retain,
                    )
                )
                ret.append(
                    MqttMessage(
                        topic=self.format_topic(name + "/mode"),
                        payload=bytes_[9],
                        retain=self.retain,
                    )
                )
                ret.append(
                    MqttMessage(
                        topic=self.format_topic(name + "/quadrant"),
                        payload=bytes_[10],
                        retain=self.retain,
                    )
                )

            yield ret
