"""Test script to control imaging from a MQTT topic."""

import asyncio
import datetime
import json
import logging
import logging.config
import time

from picamera_mqtt import deploy
from picamera_mqtt.imaging import imaging
from picamera_mqtt.mqtt_clients import AsyncioClient, message_string_encoding
from picamera_mqtt.protocol import (
    control_topic, deployment_topic, imaging_topic
)
from picamera_mqtt.util import config
from picamera_mqtt.util.async import (
    register_keyboard_interrupt_signals, run_function
)
from picamera_mqtt.util.logging import logging_config

# Set up logging
logging.config.dictConfig(logging_config)
logger = logging.getLogger(__name__)

# Configure messaging
topics = {
    control_topic: {
        'qos': 2,
        'local_namespace': True,
        'subscribe': True,
        'log': True
    },
    imaging_topic: {
        'qos': 2,
        'local_namespace': True,
        'subscribe': False,
        'log': False
    },
    deployment_topic: {
        'qos': 2,
        'local_namespace': True,
        'subscribe': True,
        'log': True
    }
}


class Imager(AsyncioClient):
    """Acquires images based on messages from the broker."""

    def __init__(self, *args, pi_username='pi', **kwargs):
        """Initialize client state."""
        super().__init__(*args, **kwargs)

        self.init_imaging()
        self.control_handlers = {
            'acquire_image': self.acquire_image,
            'update_parameters': self.update_parameters
        }

        self.pi_username = pi_username

    def init_imaging(
        self, resolution=(1640, 1232), sensor_mode=4, framerate=15, **kwargs
    ):
        """Initialize imaging support."""
        from picamera import PiCamera

        self.camera = imaging.Camera(
            PiCamera(
                resolution=resolution, sensor_mode=sensor_mode,
                framerate=framerate
            ), **kwargs
        )

    def on_disconnect(self, client, userdata, rc):
        """When the client disconnects, handle it."""
        super().on_disconnect(client, userdata, rc)

    def on_deployment_topic(self, client, userdata, msg):
        """Handle any device deployment messages."""
        command = msg.payload.decode(message_string_encoding)
        if command == 'reboot':
            self.loop.create_task(deploy.reboot())
        elif command == 'shutdown':
            self.loop.create_task(deploy.shutdown())
        elif command == 'restart':
            self.loop.create_task(deploy.restart())
        elif command == 'git pull':
            self.loop.create_task(deploy.git_pull(
                self.pi_username, restart_afterwards=True
            ))
        elif command == 'stop':
            raise KeyboardInterrupt

    def on_control_topic(self, client, userdata, msg):
        """Handle any imaging control messages."""
        payload = msg.payload.decode(message_string_encoding)
        try:
            control_command = json.loads(payload)
        except json.JSONDecodeError:
            logger.error(
                'Malformed imaging control command: {}'.format(payload)
            )
            return
        try:
            action = control_command['action']
            self.control_handlers[action]
        except (KeyError, IndexError):
            logger.error('Unknown/missing control action: {}'.format(payload))
            return
        self.run_control_command(control_command)

    def add_topic_handlers(self):
        """Add any topic handler message callbacks as needed."""
        self.client.message_callback_add(
            self.get_topic_path(deployment_topic), self.on_deployment_topic
        )
        self.client.message_callback_add(
            self.get_topic_path(control_topic), self.on_control_topic
        )

    def acquire_image(self, params):
        """Capture an image and publish it over MQTT."""
        command_time = params.get('command_time', {
            'time': time.time()
        })
        metadata = params.get('metadata', {
            'client_name': self.client_name
        })
        format = params.get('format', 'jpeg')
        capture_format_params = params.get('format_params', {
            'quality': 100
        })
        transport_format_params = params.get('format_params', {
            'quality': 80
        })
        image_pil = self.camera.capture_pil(
            format=format, **capture_format_params
        )
        image_base64 = imaging.pil_to_base64(
            image_pil, format=format, **transport_format_params
        )
        output = {
            'metadata': metadata,
            'command_time': command_time,
            'capture_time': {
                'time': time.time(),
                'datetime': str(datetime.datetime.now())
            },
            'format': format,
            'capture_format_params': capture_format_params,
            'transport_format_params': transport_format_params,
            'camera_params': self.camera.get_params(),
            'image': image_base64
        }
        output_json = json.dumps(output)
        logger.info('Publishing image to {}...'.format(
            self.get_topic_path(imaging_topic)
        ))
        self.publish_message(imaging_topic, output_json)

    def update_parameters(self, params):
        """Update camera parameters."""
        pass

    def run_control_command(self, control_command):
        """Apply an imaging control command."""
        logger.info('Running control command: {}'.format(control_command))
        action = control_command['action']
        self.control_handlers[action](control_command)

    async def attempt_reconnect(self):
        """Prepare the system for a reconnection attempt."""
        await deploy.reconnect()


if __name__ == '__main__':
    register_keyboard_interrupt_signals()

    # Load configuration
    config_path = deploy.client_config_plain_path
    configuration = config.config_load(config_path)

    logger.info('Starting client...')
    loop = asyncio.get_event_loop()
    mqttc = Imager(
        loop, **configuration['broker'], **configuration['deploy'],
        topics=topics
    )
    run_function(mqttc.run)
    logger.info('Finished!')