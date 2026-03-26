"""Matter Device Controller implementation.

This module implements the Matter Device Controller WebSocket API. Compared to the
`ChipDeviceControllerWrapper` class it adds the WebSocket specific sauce and adds more
features which are not part of the Python Matter Device Controller per-se, e.g.
pinging a device.
"""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime
from functools import cached_property, lru_cache
import logging
import re
import secrets
import time
from typing import TYPE_CHECKING, Any, cast

from chip.ChipDeviceCtrl import ChipDeviceController
from chip.clusters import Attribute, Objects as Clusters
from chip.clusters.Attribute import AttributeWriteResult, ValueDecodeFailure
from chip.clusters.ClusterObjects import ALL_ATTRIBUTES, ALL_CLUSTERS, Cluster
from chip.discovery import DiscoveryType
from chip.exceptions import ChipStackError
from chip.interaction_model import InteractionModelError
from chip.native import PyChipError
from chip.setup_payload import setup_payload
from chip.tlv import TLVReader, TLVWriter, uint as tlv_uint
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from zeroconf import (
    BadTypeInNameException,
    DNSQuestionType,
    IPVersion,
    ServiceStateChange,
    Zeroconf,
)
from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf

from matter_server.common.const import VERBOSE_LOG_LEVEL
from matter_server.common.custom_clusters import check_polled_attributes
from matter_server.common.models import (
    BLEScanResult,
    CommissionableNodeData,
    CommissioningParameters,
    MatterSoftwareVersion,
)
from matter_server.server.helpers.attributes import parse_attributes_from_read_result
from matter_server.server.helpers.utils import ping_ip
from matter_server.server.ota import check_for_update, load_local_updates
from matter_server.server.ota.provider import ExternalOtaProvider
from matter_server.server.sdk import ChipDeviceControllerWrapper

from ..common.errors import (
    InvalidArguments,
    NodeCommissionFailed,
    NodeInterviewFailed,
    NodeNotExists,
    NodeNotReady,
    NodeNotResolving,
    UpdateCheckError,
    UpdateError,
)
from ..common.helpers.api import api_command
from ..common.helpers.json import JSON_DECODE_EXCEPTIONS, json_loads
from ..common.helpers.util import (
    create_attribute_path_from_attribute,
    dataclass_from_dict,
    parse_attribute_path,
    parse_value,
)
from ..common.models import (
    APICommand,
    EventType,
    GroupListResult,
    MatterFabricInfo,
    MatterGroupInfo,
    MatterNodeData,
    MatterNodeEvent,
    NodePingResult,
    UpdateSource,
)
from .const import DATA_MODEL_SCHEMA_VERSION

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from pathlib import Path

    from .server import MatterServer

DATA_KEY_NODES = "nodes"
DATA_KEY_GROUP_KEYS = "group_keys"
DATA_KEY_NODE_KEYSETS = "node_keysets"  # node_id → [keyset_id, ...] controller-tracked
DATA_KEY_GROUP_NODES = (
    "group_nodes"  # group_id → [node_id, ...] provisioned nodes per group
)
DATA_KEY_LAST_NODE_ID = "last_node_id"
_MATTER_BLE_SERVICE_UUID = "0000fff6-0000-1000-8000-00805f9b34fb"

LOGGER = logging.getLogger(__name__)
NODE_SUBSCRIPTION_FLOOR_DEFAULT = 1
NODE_SUBSCRIPTION_FLOOR_ICD = 0
NODE_SUBSCRIPTION_CEILING_WIFI = 60
NODE_SUBSCRIPTION_CEILING_THREAD = 60
NODE_SUBSCRIPTION_CEILING_BATTERY_POWERED = 600
NODE_RESUBSCRIBE_ATTEMPTS_UNAVAILABLE = 2
NODE_RESUBSCRIBE_TIMEOUT_OFFLINE = 30 * 60
NODE_RESUBSCRIBE_FORCE_TIMEOUT = 5
NODE_PING_TIMEOUT = 10
NODE_PING_TIMEOUT_BATTERY_POWERED = 60
NODE_MDNS_SUBSCRIPTION_RETRY_TIMEOUT = 30 * 60
CUSTOM_ATTRIBUTES_POLLER_INTERVAL = 30

MDNS_TYPE_OPERATIONAL_NODE = "_matter._tcp.local."
MDNS_TYPE_COMMISSIONABLE_NODE = "_matterc._udp.local."

TEST_NODE_START = 900000

ROUTING_ROLE_ATTRIBUTE_PATH = create_attribute_path_from_attribute(
    0, Clusters.ThreadNetworkDiagnostics.Attributes.RoutingRole
)
DESCRIPTOR_PARTS_LIST_ATTRIBUTE_PATH = create_attribute_path_from_attribute(
    0, Clusters.Descriptor.Attributes.PartsList
)
BASIC_INFORMATION_VENDOR_ID_ATTRIBUTE_PATH = create_attribute_path_from_attribute(
    0, Clusters.BasicInformation.Attributes.VendorID
)
BASIC_INFORMATION_PRODUCT_ID_ATTRIBUTE_PATH = create_attribute_path_from_attribute(
    0, Clusters.BasicInformation.Attributes.ProductID
)
BASIC_INFORMATION_SOFTWARE_VERSION_ATTRIBUTE_PATH = (
    create_attribute_path_from_attribute(
        0, Clusters.BasicInformation.Attributes.SoftwareVersion
    )
)
BASIC_INFORMATION_SOFTWARE_VERSION_STRING_ATTRIBUTE_PATH = (
    create_attribute_path_from_attribute(
        0, Clusters.BasicInformation.Attributes.SoftwareVersionString
    )
)
ICD_ATTR_LIST_ATTRIBUTE_PATH = create_attribute_path_from_attribute(
    0, Clusters.IcdManagement.Attributes.AttributeList
)

RE_MDNS_SERVICE_NAME = re.compile(
    rf"^([0-9A-Fa-f]{{16}})-([0-9A-Fa-f]{{16}})\.{re.escape(MDNS_TYPE_OPERATIONAL_NODE)}$"
)


# pylint: disable=too-many-lines,too-many-instance-attributes,too-many-public-methods


class MatterDeviceController:
    """Class that manages the Matter devices."""

    def __init__(
        self,
        server: MatterServer,
        paa_root_cert_dir: Path,
        ota_provider_dir: Path,
    ):
        """Initialize the device controller."""
        self.server = server
        self._ota_provider_dir = ota_provider_dir

        self._chip_device_controller = ChipDeviceControllerWrapper(
            server, paa_root_cert_dir
        )

        # we keep the last events in memory so we can include them in the diagnostics dump
        self.event_history: deque[Attribute.EventReadResult] = deque(maxlen=25)
        self._compressed_fabric_id: int | None = None
        self._wifi_credentials_set: bool = False
        self._thread_credentials_set: bool = False
        self._wifi_credentials: tuple[str, str] | None = None
        self._thread_dataset: str | None = None
        self._setup_node_tasks = dict[int, asyncio.Task]()
        self._nodes_in_ota: set[int] = set()
        self._node_last_seen_on_mdns: dict[int, float] = {}
        self._nodes: dict[int, MatterNodeData] = {}
        self._last_known_ip_addresses: dict[int, list[str]] = {}
        self._resubscription_attempt: dict[int, int] = {}
        self._first_resubscribe_attempt: dict[int, float] = {}
        self._known_commissioning_params: dict[int, CommissioningParameters] = {}
        self._known_commissioning_params_timers: dict[int, asyncio.TimerHandle] = {}
        self._aiobrowser: AsyncServiceBrowser | None = None
        self._aiozc: AsyncZeroconf | None = None
        self._thread_node_setup_throttle = asyncio.Semaphore(5)
        self._mdns_event_timer: dict[str, asyncio.TimerHandle] = {}
        self._polled_attributes: dict[int, set[str]] = {}
        # Minimal crypto store: group_id → (keyset_id, epoch_key_hex)
        # Keys are injected into controller KVS so SendGroupCommand can encrypt frames.
        # Membership is stored on devices (via Groups cluster), NOT here.
        self._group_key_store: dict[int, tuple[int, str]] = {}
        # Controller-side keyset tracker: node_id → set of keyset_ids we have written.
        # Used as fallback source for cleanup when GroupKeyTable is unavailable on the device.
        self._known_keysets_per_node: dict[int, set[int]] = {}
        # Provisioned-nodes tracker: group_id → set of node_ids provisioned for that group.
        # Used by send_group_command to verify device-side keyset presence before multicast.
        self._group_provisioned_nodes: dict[int, set[int]] = {}
        self._custom_attribute_poller_timer: asyncio.TimerHandle | None = None
        self._custom_attribute_poller_task: asyncio.Task | None = None
        self._attribute_update_callbacks: dict[int, list[Callable]] = {}
        self._default_fabric_label: str | None = None

    async def initialize(self) -> None:
        """Initialize the device controller."""
        self._compressed_fabric_id = (
            await self._chip_device_controller.get_compressed_fabric_id()
        )
        await load_local_updates(self._ota_provider_dir)

    async def start(self) -> None:  # pylint: disable=too-many-locals
        """Handle logic on controller start."""
        # Load group crypto material from persistent storage.
        # Keys are already injected into the SDK's KVS (chip.json) from when each
        # group was first created via group_add — no re-injection needed on startup.
        # This store is used only to provision new nodes with matching keys.
        stored_keys: dict[str, dict] = self.server.storage.get(DATA_KEY_GROUP_KEYS, {})
        for group_id_str, key_dict in stored_keys.items():
            group_id = int(group_id_str)
            self._group_key_store[group_id] = (
                key_dict["keyset_id"],
                key_dict["epoch_key_hex"],
            )
        LOGGER.info("Loaded %d group key entries", len(self._group_key_store))

        # Load controller-side keyset tracking (fallback for devices without GroupKeyTable).
        stored_node_keysets: dict[str, list[int]] = self.server.storage.get(
            DATA_KEY_NODE_KEYSETS, {}
        )
        for nid_str, keyset_list in stored_node_keysets.items():
            self._known_keysets_per_node[int(nid_str)] = set(keyset_list)
        LOGGER.info(
            "Loaded keyset tracking for %d nodes", len(self._known_keysets_per_node)
        )

        # Load provisioned-nodes tracker: group_id → set of node_ids.
        stored_group_nodes: dict[str, list[int]] = self.server.storage.get(
            DATA_KEY_GROUP_NODES, {}
        )
        for gid_str, node_list in stored_group_nodes.items():
            self._group_provisioned_nodes[int(gid_str)] = set(node_list)
        LOGGER.info(
            "Loaded provisioned-nodes tracking for %d groups",
            len(self._group_provisioned_nodes),
        )

        # load nodes from persistent storage
        nodes: dict[str, dict | None] = self.server.storage.get(DATA_KEY_NODES, {})
        orphaned_nodes: set[str] = set()
        for node_id_str, node_dict in nodes.items():
            node_id = int(node_id_str)
            if node_dict is None:
                # Non-initialized (left-over) node from a failed commissioning attempt.
                # NOTE: This code can be removed in a future version
                # as this can no longer happen.
                orphaned_nodes.add(node_id_str)
                continue
            try:
                node = dataclass_from_dict(MatterNodeData, node_dict, strict=True)
            except (KeyError, ValueError):
                # constructing MatterNodeData from the cached dict is not possible,
                # revert to a fallback object and the node will be re-interviewed
                node = MatterNodeData(
                    node_id=node_id,
                    date_commissioned=node_dict.get(
                        "date_commissioned",
                        datetime(1970, 1, 1),
                    ),
                    last_interview=node_dict.get(
                        "last_interview",
                        datetime(1970, 1, 1),
                    ),
                    interview_version=0,
                )
            # always mark node as unavailable at startup until subscriptions are ready
            node.available = False
            self._nodes[node_id] = node
        # cleanup orhpaned nodes from storage
        for node_id_str in orphaned_nodes:
            self.server.storage.remove(DATA_KEY_NODES, node_id_str)
        LOGGER.info("Loaded %s nodes from stored configuration", len(self._nodes))
        # set-up mdns browser
        self._aiozc = AsyncZeroconf(ip_version=IPVersion.All)
        services = [MDNS_TYPE_OPERATIONAL_NODE, MDNS_TYPE_COMMISSIONABLE_NODE]
        self._aiobrowser = AsyncServiceBrowser(
            self._aiozc.zeroconf,
            services,
            handlers=[self._on_mdns_service_state_change],
            question_type=DNSQuestionType.QM,
        )

    async def stop(self) -> None:
        """Handle logic on server stop."""
        # shutdown (and cleanup) mdns browser
        if self._aiobrowser:
            await self._aiobrowser.async_cancel()
        if self._aiozc:
            await self._aiozc.async_close()
        # Ensure any in-progress setup tasks are cancelled
        for task in self._setup_node_tasks.values():
            task.cancel()

        # shutdown the sdk device controller
        await self._chip_device_controller.shutdown()
        LOGGER.debug("Stopped.")

    @property
    def compressed_fabric_id(self) -> int:
        """Return the compressed fabric id."""
        if self._compressed_fabric_id is None:
            raise RuntimeError("Compressed Fabric ID not set")
        return self._compressed_fabric_id

    @property
    def wifi_credentials_set(self) -> bool:
        """Return if WiFi credentials have been set."""
        return self._wifi_credentials_set

    @property
    def thread_credentials_set(self) -> bool:
        """Return if Thread operational dataset as been set."""
        return self._thread_credentials_set

    @cached_property
    def _loop(self) -> asyncio.AbstractEventLoop:
        """Return the event loop."""
        assert self.server.loop
        return self.server.loop

    @lru_cache(maxsize=1024)  # noqa: B019
    def get_node_logger(
        self, logger: logging.Logger, node_id: int
    ) -> logging.LoggerAdapter:
        """Return a logger for a specific node."""
        return logging.LoggerAdapter(logger, {"node": node_id})

    @api_command(APICommand.GET_NODES)
    def get_nodes(self, only_available: bool = False) -> list[MatterNodeData]:
        """Return all Nodes known to the server."""
        return [
            x
            for x in self._nodes.values()
            if x is not None and (x.available or not only_available)
        ]

    @api_command(APICommand.GET_NODE)
    def get_node(self, node_id: int) -> MatterNodeData:
        """Return info of a single Node."""
        if node := self._nodes.get(node_id):
            return node
        raise NodeNotExists(f"Node {node_id} does not exist or is not yet interviewed")

    @api_command(APICommand.SET_DEFAULT_FABRIC_LABEL)
    async def set_default_fabric_label(self, label: str | None) -> None:
        """Set the default fabric label."""
        if label is not None and len(label) > 32:
            LOGGER.info(
                "Fabric label '%s' exceeds 32 characters, truncating to '%s'",
                label,
                label[:32],
            )
            label = label[:32]
        self._default_fabric_label = label

    @api_command(APICommand.COMMISSION_WITH_CODE)
    async def commission_with_code(  # pylint: disable=too-many-branches
        self, code: str, network_only: bool = False, fabric_label: str | None = None
    ) -> MatterNodeData:
        """
        Commission a device using a QR Code or Manual Pairing Code.

        :param code: The QR Code or Manual Pairing Code for device commissioning.
        :param network_only: If True, restricts device discovery to network only.
        :param fabric_label: Optional label to set on this fabric entry on the device
                             (visible via get_fabrics). Useful for multi-fabric setups
                             to identify which controller owns which fabric.

        :return: The NodeInfo of the commissioned device.
        """
        if not network_only and not self.server.bluetooth_enabled:
            raise NodeCommissionFailed("Bluetooth commissioning is not available.")

        node_id = self._get_next_node_id()
        LOGGER.info(
            "Starting Matter commissioning with code using Node ID %s.",
            node_id,
        )

        discriminator, is_short_discriminator, setup_pin_code = (
            self._extract_discriminator(code)
        )

        try:
            if (
                discriminator is not None
                and setup_pin_code is not None
                and not network_only
            ):
                # If we have a discriminator and not network_only, we try BLE commissioning directly
                # as the SDK's CommissionWithCode sometimes fails to find the device over BLE
                # without an explicit discriminator.
                LOGGER.info(
                    "Attempting BLE commissioning for node %s using %s discriminator %s",
                    node_id,
                    "short" if is_short_discriminator else "long",
                    discriminator,
                )
                commissioned_node_id = (
                    await self._chip_device_controller.commission_ble(
                        node_id,
                        setup_pin_code,
                        discriminator,
                        is_short_discriminator,
                        wifi_credentials=self._wifi_credentials,
                        thread_dataset=self._thread_dataset,
                    )
                )
            else:
                commissioned_node_id = (
                    await self._chip_device_controller.commission_with_code(
                        node_id,
                        code,
                        DiscoveryType.DISCOVERY_NETWORK_ONLY
                        if network_only
                        else DiscoveryType.DISCOVERY_ALL,
                    )
                )
            # We use SDK default behavior which always uses the commissioning Node ID in the
            # generated NOC. So this should be the same really.
            LOGGER.info("Commissioned Node ID: %s vs %s", commissioned_node_id, node_id)
            if commissioned_node_id != node_id:
                raise RuntimeError("Returned Node ID must match requested Node ID")
        except ChipStackError as err:
            raise NodeCommissionFailed(
                f"Commission with code failed for node {node_id}."
            ) from err

        LOGGER.info("Matter commissioning of Node ID %s successful.", node_id)

        # perform full (first) interview of the device
        # we retry the interview max 3 times as it may fail in noisy
        # RF environments (in case of thread), mdns trouble or just flaky devices.
        # retrying both the mdns resolve and (first) interview, increases the chances
        # of a successful device commission.
        retries = 3
        while retries:
            try:
                await self._interview_node(node_id)
            except (NodeNotResolving, NodeInterviewFailed) as err:
                if retries <= 0:
                    try:
                        await self._chip_device_controller.unpair_device(node_id)
                    except ChipStackError as err_unpair:
                        LOGGER.warning(
                            "Removing current fabric from device failed: %s", err_unpair
                        )
                    raise err
                retries -= 1
                LOGGER.warning("Unable to interview Node %s: %s", node_id, err)
                await asyncio.sleep(5)
            else:
                break
        # make sure we start a subscription for this newly added node
        if task := self._setup_node_create_task(node_id):
            await task
        # Set fabric label if requested (allows identifying our fabric on multi-fabric devices)
        if fabric_label:
            try:
                await self.update_fabric_label(node_id, fabric_label)
            except Exception as err:  # noqa: BLE001  # pylint: disable=W0718
                LOGGER.warning(
                    "Failed to set fabric label for node %s: %s", node_id, err
                )
        LOGGER.info("Commissioning of Node ID %s completed.", node_id)
        # return full node object once we're complete
        return self.get_node(node_id)

    def _extract_discriminator(self, code: str) -> tuple[int | None, bool, int | None]:
        """Extract discriminator and pin from setup code (QR or manual)."""
        discriminator: int | None = None
        is_short_discriminator = False
        setup_pin_code: int | None = None
        try:
            payload = setup_payload.SetupPayload()
            if code.startswith("MT:"):
                payload.ParseQrCode(code)
            else:
                payload.ParseManualPairingCode(code)

            if payload.long_discriminator is not None:
                discriminator = payload.long_discriminator
                is_short_discriminator = False
            elif payload.short_discriminator is not None:
                discriminator = payload.short_discriminator
                is_short_discriminator = True

            setup_pin_code = payload.setup_passcode

            LOGGER.debug(
                "Extracted %s discriminator (%s) and PIN (%s) from setup code",
                "short" if is_short_discriminator else "long",
                discriminator,
                setup_pin_code,
            )
        except (ValueError, ChipStackError) as err:
            LOGGER.warning("Failed to extract discriminator from setup code: %s", err)

        return discriminator, is_short_discriminator, setup_pin_code

    @api_command(APICommand.COMMISSION_ON_NETWORK)
    async def commission_on_network(
        self,
        setup_pin_code: int,
        filter_type: int = 0,
        filter: Any = None,  # pylint: disable=redefined-builtin
        ip_addr: str | None = None,
        fabric_label: str | None = None,
    ) -> MatterNodeData:
        """
        Do the routine for OnNetworkCommissioning, with a filter for mDNS discovery.

        The filter can be an integer,
        a string or None depending on the actual type of selected filter.

        NOTE: For advanced usecases only, use `commission_with_code`
        for regular commissioning.

        :param fabric_label: Optional label to identify our fabric on the device
                             (useful for multi-fabric setups).

        Returns full NodeInfo once complete.
        """
        node_id = self._get_next_node_id()
        if ip_addr is not None:
            ip_addr = self.server.scope_ipv6_lla(ip_addr)

        try:
            if ip_addr is None:
                # regular CommissionOnNetwork if no IP address provided
                LOGGER.info(
                    "Starting Matter commissioning on network using Node ID %s.",
                    node_id,
                )
                commissioned_node_id = (
                    await self._chip_device_controller.commission_on_network(
                        node_id, setup_pin_code, filter_type, filter
                    )
                )
            else:
                LOGGER.info(
                    "Starting Matter commissioning using Node ID %s and IP %s.",
                    node_id,
                    ip_addr,
                )
                commissioned_node_id = await self._chip_device_controller.commission_ip(
                    node_id, setup_pin_code, ip_addr
                )
            # We use SDK default behavior which always uses the commissioning Node ID in the
            # generated NOC. So this should be the same really.
            if commissioned_node_id != node_id:
                raise RuntimeError("Returned Node ID must match requested Node ID")
        except ChipStackError as err:
            raise NodeCommissionFailed(
                f"Commissioning failed for node {node_id}."
            ) from err

        LOGGER.info("Matter commissioning of Node ID %s successful.", node_id)

        # perform full (first) interview of the device
        # we retry the interview max 3 times as it may fail in noisy
        # RF environments (in case of thread), mdns trouble or just flaky devices.
        # retrying both the mdns resolve and (first) interview, increases the chances
        # of a successful device commission.
        retries = 3
        while retries:
            try:
                await self._interview_node(node_id)
            except NodeInterviewFailed as err:
                if retries <= 0:
                    raise err
                retries -= 1
                LOGGER.warning("Unable to interview Node %s: %s", node_id, err)
                await asyncio.sleep(5)
            else:
                break
        # make sure we start a subscription for this newly added node
        if task := self._setup_node_create_task(node_id):
            await task
        # Set fabric label if requested (allows identifying our fabric on multi-fabric devices)
        if fabric_label:
            try:
                await self.update_fabric_label(node_id, fabric_label)
            except Exception as err:  # noqa: BLE001  # pylint: disable=W0718
                LOGGER.warning(
                    "Failed to set fabric label for node %s: %s", node_id, err
                )
        LOGGER.info("Commissioning of Node ID %s completed.", node_id)
        # return full node object once we're complete
        return self.get_node(node_id)

    @api_command(APICommand.COMMISSION_ON_COMMISSIONING_WINDOW)
    async def commission_on_commissioning_window(
        self,
        setup_pin_code: int,
        discriminator: int,
        ip_addr: str | None = None,
        fabric_label: str | None = None,
    ) -> MatterNodeData:
        """Commission a device that has an open commissioning window from another fabric.

        This is the explicit Multi-Fabric Commissioning path. Use this when a device is already
        commissioned to a different Matter controller/fabric, and that controller has called
        open_commissioning_window to share the device. Pass the setup_pin_code and discriminator
        returned by the other controller's open_commissioning_window call.

        The full multi-fabric flow:
          1. Device is already on Fabric A (another controller).
          2. Fabric A calls open_commissioning_window(node_id) → returns CommissioningParameters.
          3. Fabric A shares setup_pin_code and discriminator (or manual/QR code) with you.
          4. You call this command → device is now on both Fabric A AND your fabric.

        To share YOUR device to another fabric: call open_commissioning_window(node_id) on
        your side and share the returned CommissioningParameters with the other controller.

        :param setup_pin_code: The setup PIN code from open_commissioning_window result.
        :param discriminator: The discriminator from open_commissioning_window result.
        :param ip_addr: Optional direct IP address (skips mDNS discovery, faster).
        :param fabric_label: Optional label to identify our fabric on the device.
                             Visible in get_fabrics() result. Max 32 chars.
        :return: The commissioned MatterNodeData.
        """
        from chip.discovery import FilterType  # noqa: PLC0415  # pylint: disable=C0415

        LOGGER.info(
            "Starting multi-fabric commissioning with discriminator=%s pin=%s",
            discriminator,
            setup_pin_code,
        )
        node_id = self._get_next_node_id()

        if ip_addr is not None:
            ip_addr = self.server.scope_ipv6_lla(ip_addr)

        try:
            if ip_addr is None:
                commissioned_node_id = (
                    await self._chip_device_controller.commission_on_network(
                        node_id,
                        setup_pin_code,
                        FilterType.LONG_DISCRIMINATOR,
                        discriminator,
                    )
                )
            else:
                commissioned_node_id = await self._chip_device_controller.commission_ip(
                    node_id, setup_pin_code, ip_addr
                )
            if commissioned_node_id != node_id:
                raise RuntimeError("Returned Node ID must match requested Node ID")
        except ChipStackError as err:
            raise NodeCommissionFailed(
                f"Multi-fabric commissioning failed for node {node_id}."
            ) from err

        LOGGER.info("Multi-fabric commissioning of Node ID %s successful.", node_id)

        retries = 3
        while retries:
            try:
                await self._interview_node(node_id)
            except NodeInterviewFailed as err:
                if retries <= 0:
                    raise err
                retries -= 1
                LOGGER.warning("Unable to interview Node %s: %s", node_id, err)
                await asyncio.sleep(5)
            else:
                break

        if task := self._setup_node_create_task(node_id):
            await task

        if fabric_label:
            try:
                await self.update_fabric_label(node_id, fabric_label)
            except Exception as err:  # noqa: BLE001  # pylint: disable=W0718
                LOGGER.warning(
                    "Failed to set fabric label for node %s: %s", node_id, err
                )

        LOGGER.info(
            "Multi-fabric commissioning of Node ID %s completed. "
            "Device is now on multiple fabrics.",
            node_id,
        )
        return self.get_node(node_id)

    @api_command(APICommand.SET_WIFI_CREDENTIALS)
    async def set_wifi_credentials(self, ssid: str, credentials: str) -> None:
        """Set WiFi credentials for commissioning to a (new) device."""

        await self._chip_device_controller.set_wifi_credentials(ssid, credentials)
        self._wifi_credentials = (ssid, credentials)
        self._wifi_credentials_set = True
        self.server.signal_event(EventType.SERVER_INFO_UPDATED, self.server.get_info())

    @api_command(APICommand.SET_THREAD_DATASET)
    async def set_thread_operational_dataset(self, dataset: str) -> None:
        """Set Thread Operational dataset in the stack."""

        await self._chip_device_controller.set_thread_operational_dataset(dataset)
        self._thread_dataset = dataset
        self._thread_credentials_set = True
        self.server.signal_event(EventType.SERVER_INFO_UPDATED, self.server.get_info())

    @api_command(APICommand.OPEN_COMMISSIONING_WINDOW)
    async def open_commissioning_window(
        self,
        node_id: int,
        timeout: int = 300,  # noqa: ASYNC109 timeout parameter required for native timeout
        iteration: int = 1000,
        option: int = ChipDeviceController.CommissioningWindowPasscode.kTokenWithRandomPin,
        discriminator: int | None = None,
    ) -> CommissioningParameters:
        """Open a commissioning window to commission a device present on this controller to another.

        Returns code to use as discriminator.
        """
        if (node := self._nodes.get(node_id)) is None or not node.available:
            raise NodeNotReady(f"Node {node_id} is not (yet) available.")

        read_response: Attribute.AsyncReadTransaction.ReadResponse = (
            await self._chip_device_controller.read_attribute(
                node_id,
                [(0, Clusters.AdministratorCommissioning.Attributes.WindowStatus)],
            )
        )
        window_status = cast(
            Clusters.AdministratorCommissioning.Enums.CommissioningWindowStatusEnum,
            read_response.attributes[0][Clusters.AdministratorCommissioning][
                Clusters.AdministratorCommissioning.Attributes.WindowStatus
            ],
        )

        if (
            window_status
            == Clusters.AdministratorCommissioning.Enums.CommissioningWindowStatusEnum.kWindowNotOpen
        ):
            # Commissioning window is no longer open (e.g. device got paired already)
            # Remove our stored commissioning parameters.
            if node_id in self._known_commissioning_params_timers:
                self._known_commissioning_params_timers[node_id].cancel()
            self._known_commissioning_params.pop(node_id, None)
        else:
            # Node is still in commissioning mode, return previous parameters
            if node_id in self._known_commissioning_params:
                return self._known_commissioning_params[node_id]

            # We restarted or somebody else put node into commissioning mode
            # Close commissioning window and put into commissioning mode again.
            LOGGER.info(
                "Commissioning window open but no parameters available. Closing and reopening commissioning window for node %s",
                node_id,
            )
            await self._chip_device_controller.send_command(
                node_id,
                endpoint_id=0,
                command=Clusters.AdministratorCommissioning.Commands.RevokeCommissioning(),
                timed_request_timeout_ms=5000,
            )

        if discriminator is None:
            discriminator = secrets.randbelow(2**12)

        sdk_result = await self._chip_device_controller.open_commissioning_window(
            node_id,
            timeout,
            iteration,
            discriminator,
            option,
        )
        self._known_commissioning_params[node_id] = params = CommissioningParameters(
            setup_pin_code=sdk_result.setupPinCode,
            setup_manual_code=sdk_result.setupManualCode,
            setup_qr_code=sdk_result.setupQRCode,
        )
        # we store the commission parameters and clear them after the timeout
        self._known_commissioning_params_timers[node_id] = self._loop.call_later(
            timeout, self._known_commissioning_params.pop, node_id, None
        )
        return params

    @api_command(APICommand.DISCOVER)
    async def discover_commissionable_nodes(
        self,
    ) -> list[CommissionableNodeData]:
        """Discover Commissionable Nodes (discovered on BLE or mDNS)."""
        sdk_result = await self._chip_device_controller.discover_commissionable_nodes()
        LOGGER.debug("SDK discovery result: %s", sdk_result)
        if sdk_result is None:
            return []
        # ensure list
        if not isinstance(sdk_result, list):
            sdk_result = [sdk_result]

        # Ensure all items are awaited if they are coroutines and flatten results
        resolved_results = []
        for x in sdk_result:
            if asyncio.iscoroutine(x):
                x = await x

            if isinstance(x, list):
                resolved_results.extend(x)
            elif x is not None:
                resolved_results.append(x)

        LOGGER.debug("Resolved discovery results: %s", resolved_results)

        return [
            CommissionableNodeData(
                instance_name=x.instanceName,
                host_name=x.hostName,
                port=x.port,
                long_discriminator=x.longDiscriminator,
                vendor_id=x.vendorId,
                product_id=x.productId,
                commissioning_mode=x.commissioningMode,
                device_type=x.deviceType,
                device_name=x.deviceName,
                pairing_instruction=x.pairingInstruction,
                pairing_hint=x.pairingHint,
                mrp_retry_interval_idle=x.mrpRetryIntervalIdle,
                mrp_retry_interval_active=x.mrpRetryIntervalActive,
                # TCP is provisional, so no devices out there anyway
                supports_tcp=False,
                addresses=x.addresses,
                rotating_id=x.rotatingId,
            )
            for x in resolved_results
        ]

    @staticmethod
    def _format_ble_bytes(data: bytes) -> str:
        """Format bytes as a space-separated hex string."""
        return " ".join(f"{b:02X}" for b in data)

    @staticmethod
    def _parse_matter_adv_data(
        data: bytes,
    ) -> tuple[int | None, int | None, int | None]:
        """Parse Matter BLE service data (fff6) and return (discriminator, vendor_id, product_id).

        Matter Core Spec §5.4.2.5 BLE payload layout (8 bytes):
          Byte 0:   flags (bit 0 = has additional data flag)
          Bits 4-15 (across bytes 0-1): 12-bit discriminator
          Bytes 2-3: Vendor ID (little-endian)
          Bytes 4-5: Product ID (little-endian)
        """
        if len(data) < 8:
            return None, None, None
        discriminator = ((data[1] & 0x0F) << 8) | (data[0] >> 4)
        vendor_id = data[2] | (data[3] << 8)
        product_id = data[4] | (data[5] << 8)
        return discriminator, vendor_id, product_id

    @api_command(APICommand.SCAN_BLE_DEVICES)
    async def scan_ble_devices(  # pylint: disable=too-many-locals
        self,
        mac_address: str | None = None,
        scan_timeout: float = 5.0,
    ) -> list[BLEScanResult]:
        """Scan for nearby BLE devices and return raw advertisement data.

        :param mac_address: If provided, only return results for this MAC address.
        :param scan_timeout: Scan duration in seconds. Use 20-30s for reliable discovery
                        since Matter devices advertise periodically.
        :return: List of BLEScanResult. When is_matter=True the device is in
                 Matter commissioning mode and can be commissioned via commission_with_mac.
        """
        try:
            from bleak import BleakScanner  # noqa: PLC0415  # pylint: disable=C0415
        except ImportError as err:
            raise RuntimeError(
                "bleak library is required for BLE scanning. "
                "Install it with: pip install bleak"
            ) from err

        mac_filter = mac_address.lower() if mac_address else None

        LOGGER.info(
            "Starting BLE scan (timeout=%.1fs, mac_filter=%s)",
            scan_timeout,
            mac_filter or "none",
        )
        devices = await BleakScanner.discover(timeout=scan_timeout, return_adv=True)

        results = []
        for address, (device, adv) in devices.items():
            if mac_filter and address.lower() != mac_filter:
                continue

            is_matter = False
            discriminator = vendor_id = product_id = None
            for uuid, svc_data in (adv.service_data or {}).items():
                if _MATTER_BLE_SERVICE_UUID in uuid.lower():
                    is_matter = True
                    discriminator, vendor_id, product_id = self._parse_matter_adv_data(
                        svc_data
                    )

            results.append(
                BLEScanResult(
                    address=device.address,
                    name=device.name,
                    rssi=adv.rssi,
                    service_uuids=list(adv.service_uuids or []),
                    service_data={
                        k: self._format_ble_bytes(v)
                        for k, v in (adv.service_data or {}).items()
                    },
                    manufacturer_data={
                        k: self._format_ble_bytes(v)
                        for k, v in (adv.manufacturer_data or {}).items()
                    },
                    is_matter=is_matter,
                    matter_discriminator=discriminator,
                    matter_vendor_id=vendor_id,
                    matter_product_id=product_id,
                )
            )

        LOGGER.debug("BLE scan found %s device(s) matching filter", len(results))
        return results

    @api_command(APICommand.COMMISSION_WITH_MAC)
    async def commission_with_mac(  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
        self,
        mac_address: str,
        setup_pin_code: int,
        scan_timeout: float = 30.0,
        fabric_label: str | None = None,
    ) -> MatterNodeData:
        """Commission a Matter device by its BLE MAC address and setup PIN code.

        Scans for the device (up to scan_timeout seconds), extracts the discriminator
        from the Matter BLE advertisement (fff6 service data), then commissions it
        using any pre-set WiFi/Thread credentials.

        The device MUST be in commissioning mode (fff6 service UUID present).
        Set WiFi/Thread credentials first via set_wifi_credentials / set_thread_dataset.

        :param mac_address: BLE MAC address of the target device (e.g. "50:3D:D1:C0:5B:AB").
        :param setup_pin_code: The device's setup PIN code (from device label or QR code).
        :param scan_timeout: How long to scan for the device in seconds (default 30.0).
        :param fabric_label: Optional label to identify our fabric on the device.
        :return: The commissioned MatterNodeData.
        """
        if not self.server.bluetooth_enabled:
            raise NodeCommissionFailed(
                "Bluetooth commissioning is not available on this server."
            )

        try:
            from bleak import BleakScanner  # noqa: PLC0415  # pylint: disable=C0415
        except ImportError as err:
            raise RuntimeError(
                "bleak library is required for BLE scanning. "
                "Install it with: pip install bleak"
            ) from err

        mac_filter = mac_address.lower()

        LOGGER.info(
            "Scanning for BLE device %s to commission (timeout=%.1fs)",
            mac_address,
            scan_timeout,
        )
        devices = await BleakScanner.discover(timeout=scan_timeout, return_adv=True)

        target_device = None
        discriminator = None
        for address, (device, adv) in devices.items():
            if address.lower() != mac_filter:
                continue
            for uuid, svc_data in (adv.service_data or {}).items():
                if _MATTER_BLE_SERVICE_UUID in uuid.lower():
                    discriminator, _, _ = self._parse_matter_adv_data(svc_data)
                    target_device = device
                    break
            if target_device:
                break

        if target_device is None:
            raise NodeCommissionFailed(
                f"Device {mac_address} was not found during BLE scan. "
                "Ensure the device is powered on, in range, and try increasing scan_timeout."
            )

        if discriminator is None:
            raise NodeCommissionFailed(
                f"Device {mac_address} is not in Matter commissioning mode "
                "(no fff6 Matter service UUID in advertisement). "
                "Hold the device button to open a commissioning window, then retry."
            )

        LOGGER.info(
            "Found device %s (name=%s) with discriminator=%s. Commissioning as node...",
            mac_address,
            target_device.name,
            discriminator,
        )

        node_id = self._get_next_node_id()
        try:
            commissioned_node_id = await self._chip_device_controller.commission_ble(
                node_id=node_id,
                setup_pin_code=setup_pin_code,
                discriminator=discriminator,
                is_short_discriminator=False,
                wifi_credentials=self._wifi_credentials,
                thread_dataset=self._thread_dataset,
            )
        except ChipStackError as err:
            raise NodeCommissionFailed(
                f"BLE commissioning failed for device {mac_address} (node {node_id})."
            ) from err

        if commissioned_node_id != node_id:
            raise RuntimeError("Returned Node ID must match requested Node ID")

        LOGGER.info("Matter commissioning of Node ID %s successful.", node_id)

        retries = 3
        while retries:
            try:
                await self._interview_node(node_id)
            except (NodeNotResolving, NodeInterviewFailed) as err:
                if retries <= 0:
                    try:
                        await self._chip_device_controller.unpair_device(node_id)
                    except ChipStackError as err_unpair:
                        LOGGER.warning(
                            "Removing current fabric from device failed: %s", err_unpair
                        )
                    raise err
                retries -= 1
                LOGGER.warning("Unable to interview Node %s: %s", node_id, err)
                await asyncio.sleep(5)
            else:
                break

        if task := self._setup_node_create_task(node_id):
            await task

        # Set fabric label if requested
        if fabric_label:
            try:
                await self.update_fabric_label(node_id, fabric_label)
            except Exception as err:  # noqa: BLE001  # pylint: disable=W0718
                LOGGER.warning(
                    "Failed to set fabric label for node %s: %s", node_id, err
                )

        LOGGER.info(
            "Commissioning of Node ID %s via MAC %s completed.", node_id, mac_address
        )
        return self.get_node(node_id)

    async def _interview_node(self, node_id: int) -> None:
        try:
            LOGGER.info("Interviewing node: %s", node_id)
            read_response: Attribute.AsyncReadTransaction.ReadResponse = (
                await self._chip_device_controller.read_attribute(
                    node_id,
                    [()],
                    fabric_filtered=False,
                )
            )
        except ChipStackError as err:
            raise NodeInterviewFailed(f"Failed to interview node {node_id}") from err

        # Set label if specified and needed
        if self._default_fabric_label:
            cluster = read_response.attributes[0][Clusters.OperationalCredentials]
            fabrics: list[
                Clusters.OperationalCredentials.Structs.FabricDescriptorStruct
            ] = cluster[Clusters.OperationalCredentials.Attributes.Fabrics]
            fabric_index = cluster[
                Clusters.OperationalCredentials.Attributes.CurrentFabricIndex
            ]

            local_fabric = next(
                (fabric for fabric in fabrics if fabric.fabricIndex == fabric_index),
                None,
            )
            if local_fabric and local_fabric.label != self._default_fabric_label:
                try:
                    LOGGER.debug(
                        "Setting fabric label for node %s to '%s'",
                        node_id,
                        self._default_fabric_label,
                    )
                    await self._chip_device_controller.send_command(
                        node_id,
                        0,
                        Clusters.OperationalCredentials.Commands.UpdateFabricLabel(
                            self._default_fabric_label
                        ),
                    )
                except ChipStackError as err:
                    LOGGER.warning(
                        "Failed to set fabric label for node %s: %s", node_id, err
                    )

        is_new_node = node_id not in self._nodes
        existing_info = self._nodes.get(node_id)
        node = MatterNodeData(
            node_id=node_id,
            date_commissioned=(
                existing_info.date_commissioned if existing_info else datetime.utcnow()
            ),
            last_interview=datetime.utcnow(),
            interview_version=DATA_MODEL_SCHEMA_VERSION,
            available=existing_info.available if existing_info else False,
            attributes=parse_attributes_from_read_result(read_response.tlvAttributes),
        )

        if existing_info:
            node.attribute_subscriptions = existing_info.attribute_subscriptions
        # work out if the node is a bridge device by looking at the devicetype of endpoint 1
        if attr_data := node.attributes.get("1/29/0"):
            node.is_bridge = any(x[0] == 14 for x in attr_data)

        # save updated node data
        self._nodes[node_id] = node
        self._write_node_state(node_id, True)
        if is_new_node:
            # new node - first interview
            self.server.signal_event(EventType.NODE_ADDED, node)
        else:
            # existing node, signal node updated event
            # TODO: maybe only signal this event if attributes actually changed ?
            self.server.signal_event(EventType.NODE_UPDATED, node)

        LOGGER.debug("Interview of node %s completed", node_id)

    @api_command(APICommand.INTERVIEW_NODE)
    async def interview_node(self, node_id: int) -> None:
        """Interview a node."""
        if node_id >= TEST_NODE_START:
            LOGGER.debug(
                "interview_node called for test node %s",
                node_id,
            )
            self.server.signal_event(EventType.NODE_UPDATED, self._nodes[node_id])
            return

        await self._interview_node(node_id)

        if self._default_fabric_label:
            await self._chip_device_controller.send_command(
                node_id,
                0,
                Clusters.OperationalCredentials.Commands.UpdateFabricLabel(
                    self._default_fabric_label
                ),
            )

    @api_command(APICommand.DEVICE_COMMAND)
    async def send_device_command(
        self,
        node_id: int,
        endpoint_id: int,
        cluster_id: int,
        command_name: str,
        payload: dict,
        response_type: Any | None = None,
        timed_request_timeout_ms: int | None = None,
        interaction_timeout_ms: int | None = None,
    ) -> Any:
        """Send a command to a Matter node/device."""
        if (node := self._nodes.get(node_id)) is None or not node.available:
            raise NodeNotReady(f"Node {node_id} is not (yet) available.")
        cluster_cls: Cluster = ALL_CLUSTERS[cluster_id]
        command_cls = getattr(cluster_cls.Commands, command_name)
        command = dataclass_from_dict(command_cls, payload, allow_sdk_types=True)
        if node_id >= TEST_NODE_START:
            LOGGER.debug(
                "send_device_command called for test node %s on endpoint_id: %s - "
                "cluster_id: %s - command_name: %s - payload: %s\n%s",
                node_id,
                endpoint_id,
                cluster_id,
                command_name,
                payload,
                command,
            )
            return None
        return await self._chip_device_controller.send_command(
            node_id,
            endpoint_id,
            command,
            response_type,
            timed_request_timeout_ms,
            interaction_timeout_ms,
        )

    @api_command(APICommand.READ_ATTRIBUTE)
    async def read_attribute(
        self,
        node_id: int,
        attribute_path: str | list[str],
        fabric_filtered: bool = False,
    ) -> dict[str, Any]:
        """
        Read one or more attribute(s) on a node by specifying an attributepath.

        The attribute path can be a single string or a list of strings.
        The attribute path may contain wildcards (*) for cluster and/or attribute id.

        The return type is a dictionary with the attribute path as key and the value as value.
        """
        if (node := self._nodes.get(node_id)) is None or not node.available:
            raise NodeNotReady(f"Node {node_id} is not (yet) available.")
        attribute_paths = (
            attribute_path if isinstance(attribute_path, list) else [attribute_path]
        )

        # handle test node
        if node_id >= TEST_NODE_START:
            LOGGER.debug(
                "read_attribute called for test node %s on path(s): %s - fabric_filtered: %s",
                node_id,
                str(attribute_paths),
                fabric_filtered,
            )
            return {
                attr_path: self._nodes[node_id].attributes.get(attr_path)
                for attr_path in attribute_paths
            }

        LOGGER.debug(
            "read_attribute called for node %s on path(s): %s - fabric_filtered: %s",
            node_id,
            str(attribute_paths),
            fabric_filtered,
        )
        # parse text based attribute paths into the SDK Attribute Path objects
        attributes: list[Attribute.AttributePath] = []
        for attr_path in attribute_paths:
            endpoint_id, cluster_id, attribute_id = parse_attribute_path(attr_path)
            attributes.append(
                Attribute.AttributePath(
                    EndpointId=endpoint_id,
                    ClusterId=cluster_id,
                    AttributeId=attribute_id,
                )
            )

        result = await self._chip_device_controller.read(
            node_id,
            attributes,
            fabric_filtered,
        )
        read_atributes = parse_attributes_from_read_result(result.tlvAttributes)
        # update cached info in node attributes and signal events for updated attributes
        values_changed = False
        for attr_path, value in read_atributes.items():
            if node.attributes.get(attr_path) != value:
                node.attributes[attr_path] = value
                self.server.signal_event(
                    EventType.ATTRIBUTE_UPDATED,
                    # send data as tuple[node_id, attribute_path, new_value]
                    (node_id, attr_path, value),
                )

                values_changed = True
        # schedule writing of the node state if any values changed
        if values_changed:
            self._write_node_state(node_id)
        return read_atributes

    @api_command(APICommand.WRITE_ATTRIBUTE)
    async def write_attribute(
        self,
        node_id: int,
        attribute_path: str,
        value: Any,
    ) -> Any:
        """Write an attribute(value) on a target node."""
        if (node := self._nodes.get(node_id)) is None or not node.available:
            raise NodeNotReady(f"Node {node_id} is not (yet) available.")
        endpoint_id, cluster_id, attribute_id = parse_attribute_path(attribute_path)
        if endpoint_id is None:
            raise InvalidArguments(f"Invalid attribute path: {attribute_path}")
        attribute = cast(
            Clusters.ClusterAttributeDescriptor,
            ALL_ATTRIBUTES[cluster_id][attribute_id](),
        )
        attribute.value = parse_value(
            name=attribute_path,
            value=value,
            value_type=attribute.attribute_type.Type,
            allow_none=False,
            allow_sdk_types=True,
        )
        if node_id >= TEST_NODE_START:
            LOGGER.debug(
                "write_attribute called for test node %s on path %s - value %s\n%s",
                node_id,
                attribute_path,
                value,
                attribute,
            )
            return None
        return await self._chip_device_controller.write_attribute(
            node_id, [(endpoint_id, attribute)]
        )

    @api_command(APICommand.REMOVE_NODE)
    async def remove_node(self, node_id: int) -> None:
        """Remove a Matter node/device from the fabric."""
        if node_id not in self._nodes:
            raise NodeNotExists(
                f"Node {node_id} does not exist or has not been interviewed."
            )

        LOGGER.info("Removing Node ID %s.", node_id)

        if task := self._setup_node_tasks.pop(node_id, None):
            task.cancel()

        # shutdown any existing subscriptions
        await self._chip_device_controller.shutdown_subscription(node_id)
        self._polled_attributes.pop(node_id, None)

        node = self._nodes.pop(node_id)
        self.server.storage.remove(
            DATA_KEY_NODES,
            subkey=str(node_id),
        )

        LOGGER.info("Node ID %s successfully removed from Matter server.", node_id)

        self.server.signal_event(EventType.NODE_REMOVED, node_id)

        if node is None or node_id >= TEST_NODE_START:
            return

        try:
            await self._chip_device_controller.unpair_device(node_id)
        except ChipStackError as err:
            LOGGER.warning("Removing current fabric from device failed: %s", err)

    @api_command(APICommand.SET_ACL_ENTRY)
    async def set_acl_entry(
        self,
        node_id: int,
        entry: list[Clusters.AccessControl.Structs.AccessControlEntryStruct],
    ) -> list[AttributeWriteResult] | None:
        """Set acl entry"""
        return await self._chip_device_controller.write_attribute(
            node_id, [(0, Clusters.AccessControl.Attributes.Acl(entry))]
        )

    @api_command(APICommand.SET_NODE_BINDING)
    async def set_node_binding(
        self,
        node_id: int,
        endpoint: int,
        bindings: list[Clusters.Binding.Structs.TargetStruct],
    ) -> list[AttributeWriteResult] | None:
        """Set node binding"""
        return await self._chip_device_controller.write_attribute(
            node_id, [(endpoint, Clusters.Binding.Attributes.Binding(bindings))]
        )

    @api_command(APICommand.BINDING_ADD)
    async def binding_add(
        self,
        node_id: int,
        endpoint_id: int,
        target_node_id: int,
        target_endpoint_id: int,
        cluster_id: int,
    ) -> list[AttributeWriteResult] | None:
        """Add a binding to a node."""
        # Read current bindings
        read_result = await self._chip_device_controller.read_attribute(
            node_id, [(endpoint_id, Clusters.Binding.Attributes.Binding)]
        )
        if read_result is None:
            return None

        current_bindings: list[Clusters.Binding.Structs.TargetStruct] = (
            read_result.attributes[endpoint_id][Clusters.Binding][
                Clusters.Binding.Attributes.Binding
            ]
        )

        # Check if already exists
        for b in current_bindings:
            if (
                b.node == target_node_id
                and b.endpoint == target_endpoint_id
                and b.cluster == cluster_id
            ):
                return None

        # Add new binding
        current_bindings.append(
            Clusters.Binding.Structs.TargetStruct(
                node=target_node_id, endpoint=target_endpoint_id, cluster=cluster_id
            )
        )
        return await self.set_node_binding(node_id, endpoint_id, current_bindings)

    @api_command(APICommand.BINDING_REMOVE)
    async def binding_remove(
        self,
        node_id: int,
        endpoint_id: int,
        target_node_id: int,
        target_endpoint_id: int,
        cluster_id: int,
    ) -> list[AttributeWriteResult] | None:
        """Remove a binding from a node."""
        # Read current bindings
        read_result = await self._chip_device_controller.read_attribute(
            node_id, [(endpoint_id, Clusters.Binding.Attributes.Binding)]
        )
        if read_result is None:
            return None

        current_bindings: list[Clusters.Binding.Structs.TargetStruct] = (
            read_result.attributes[endpoint_id][Clusters.Binding][
                Clusters.Binding.Attributes.Binding
            ]
        )

        # Remove binding
        new_bindings = [
            b
            for b in current_bindings
            if not (
                b.node == target_node_id
                and b.endpoint == target_endpoint_id
                and b.cluster == cluster_id
            )
        ]

        if len(new_bindings) == len(current_bindings):
            return None

        return await self.set_node_binding(node_id, endpoint_id, new_bindings)

    @api_command(APICommand.GROUP_ADD)
    async def group_add(
        self, node_id: int, endpoint: int, group_id: int, group_name: str
    ) -> None:
        """Add a node endpoint to a group.

        Follows the Matter spec:
        1. Validates Groups cluster support via Descriptor.ServerList.
        2. Generates and stores group encryption keys (first time only).
        3. Injects keys into the controller's GroupDataProvider (KVS).
        4. Provisions the node via GroupKeyManagement (keyset reuse-first, see
           _provision_group_keys_on_node for the full algorithm).
        5. Sends Groups.AddGroup to the device endpoint.

        Group membership is authoritative on the device, not on the server.
        """
        # 1. Validate that the endpoint supports the Groups cluster.
        if not await self._endpoint_supports_groups(node_id, endpoint):
            raise InvalidArguments(
                f"Endpoint {endpoint} on node {node_id} does not support the Groups cluster "
                "(not listed in Descriptor.ServerList). "
                "Check the endpoint ID or verify the device capabilities."
            )

        # 2. Generate keys for this group if we have not seen it before.
        if group_id not in self._group_key_store:
            keyset_id = (group_id % 0xFFFE) + 1  # avoids 0 (IPK) and 0xFFFF (invalid)
            epoch_key_hex = secrets.token_bytes(16).hex()
            # 3. Inject into controller KVS so SendGroupCommand can encrypt frames.
            self._inject_controller_group_keys(group_id, keyset_id, epoch_key_hex)
            # Persist crypto material so we can provision future nodes joining this group.
            self._group_key_store[group_id] = (keyset_id, epoch_key_hex)
            self.server.storage.set(
                DATA_KEY_GROUP_KEYS,
                {"keyset_id": keyset_id, "epoch_key_hex": epoch_key_hex},
                subkey=str(group_id),
            )

        keyset_id, epoch_key_hex = self._group_key_store[group_id]

        # 4. Check device group-table capacity before provisioning keys.
        #    If the group is already a member we can skip this (AddGroup is idempotent).
        existing_groups, remaining_cap = await self._get_group_membership_and_capacity(
            node_id, endpoint
        )
        if group_id not in existing_groups and remaining_cap == 0:
            # Table is full — evict the oldest group (FIFO) to free a slot.
            if existing_groups:
                evict_id = existing_groups[0]
                LOGGER.info(
                    "Group table full on node %s endpoint %s — evicting group %s (FIFO) "
                    "to make room for group %s",
                    node_id,
                    endpoint,
                    evict_id,
                    group_id,
                )
                await self._chip_device_controller.send_command(
                    node_id,
                    endpoint,
                    Clusters.Groups.Commands.RemoveGroup(groupID=evict_id),
                )
            else:
                raise InvalidArguments(
                    f"Cannot add group {group_id} on node {node_id} endpoint {endpoint}: "
                    "group table is reported as full but no existing groups were returned."
                )

        # 5. Provision the node (reads device state first, reuses keysets where
        #    possible, handles ResourceExhausted gracefully).
        try:
            await self._provision_group_keys_on_node(
                node_id, group_id, keyset_id, epoch_key_hex
            )
        except (ChipStackError, InteractionModelError) as err:
            LOGGER.warning(
                "Failed to provision node %s with group keys — groupcast to this node "
                "may not work until keys are provisioned: %s",
                node_id,
                err,
            )

        # 6. Send Groups.AddGroup to the device (Matter spec §11.2.6.1).
        await self._chip_device_controller.send_command(
            node_id,
            endpoint,
            Clusters.Groups.Commands.AddGroup(groupID=group_id, groupName=group_name),
            timed_request_timeout_ms=5000,
        )

        # 7. Record that this node is provisioned for the group so that
        #    send_group_command can verify device-side keyset presence before multicast.
        provisioned = self._group_provisioned_nodes.setdefault(group_id, set())
        provisioned.add(node_id)
        self.server.storage.set(
            DATA_KEY_GROUP_NODES, sorted(provisioned), subkey=str(group_id)
        )

    async def _get_group_membership_and_capacity(
        self, node_id: int, endpoint: int
    ) -> tuple[list[int], int | None]:
        """Return (group_ids, remaining_capacity) from Groups.GetGroupMembership.

        Queries the device via the Groups cluster.  remaining_capacity is None when
        the device reports an unknown/null capacity value.
        """
        resp = await self._chip_device_controller.send_command(
            node_id,
            endpoint,
            Clusters.Groups.Commands.GetGroupMembership(groupList=[]),
        )
        group_ids: list[int] = list(resp.groupList)
        raw_cap = resp.capacity
        # The Matter spec uses nullable uint8 for capacity; the SDK may return None
        # or a Null sentinel.  Treat anything that is not a plain int as unknown.
        remaining: int | None = raw_cap if isinstance(raw_cap, int) else None
        return group_ids, remaining

    def _record_keyset_on_node(self, node_id: int, keyset_id: int) -> None:
        """Mark keyset_id as present on node_id in the controller tracker.

        Called whenever we confirm a keyset is installed (skipped write, reuse, etc.)
        so that cleanup has accurate state even when GroupKeyTable is unavailable.
        """
        tracked = self._known_keysets_per_node.setdefault(node_id, set())
        if keyset_id not in tracked:
            tracked.add(keyset_id)
            self.server.storage.set(
                DATA_KEY_NODE_KEYSETS, sorted(tracked), subkey=str(node_id)
            )

    async def _cleanup_unused_keysets_on_node(self, node_id: int) -> int:
        """Remove keysets on node that are no longer referenced by any group.

        Matter rule: RemoveAllGroups / RemoveGroup clear the group table but do NOT
        remove keysets.  Orphaned keysets accumulate and eventually fill the device's
        fixed-size keyset table (typically 3 slots), causing ResourceExhausted on the
        next KeySetWrite.

        Algorithm:
          1. Read GroupKeyTable (all provisioned keysets, fabric-scoped).
          2. Read GroupKeyMap  (all group→keyset bindings, fabric-scoped).
          3. Any keyset in GroupKeyTable that is NOT referenced by GroupKeyMap
             (and is NOT the IPK, keyset_id=0) is orphaned → remove via KeySetRemove.

        Returns the number of keysets successfully removed.
        """
        # 1. Get all provisioned keyset IDs — try GroupKeyTable on device first.
        #    Many consumer devices (e.g. Tapo) do not expose GroupKeyTable; fall
        #    back to the controller-tracked set in that case.
        all_keyset_ids: set[int] = set()
        try:
            table_result = await self._chip_device_controller.read_attribute(
                node_id=node_id,
                attributes=[
                    (0, Clusters.GroupKeyManagement.Attributes.GroupKeyTable)  # pylint: disable=no-member
                ],
            )
            if table_result is not None and table_result.attributes is not None:
                all_keyset_ids = {
                    entry.groupKeySetID
                    for entry in table_result.attributes[0][
                        Clusters.GroupKeyManagement
                    ][
                        Clusters.GroupKeyManagement.Attributes.GroupKeyTable  # pylint: disable=no-member
                    ]
                }
        except Exception:  # noqa: BLE001, S110  # pylint: disable=W0718
            pass  # GroupKeyTable unavailable — fallback applied below

        if not all_keyset_ids:
            # Device did not expose GroupKeyTable — use the controller-side tracker.
            all_keyset_ids = set(self._known_keysets_per_node.get(node_id, set()))
            if all_keyset_ids:
                LOGGER.debug(
                    "GroupKeyTable unavailable on node %s — "
                    "using controller-tracked keysets for cleanup: %s",
                    node_id,
                    all_keyset_ids,
                )
            else:
                LOGGER.debug(
                    "No keyset information available for node %s — skipping cleanup",
                    node_id,
                )
                return 0

        # 2. Find which keysets are still referenced by a group binding.
        entries = await self._get_node_group_key_map(node_id)
        referenced_ids: set[int] = {e.groupKeySetID for e in entries}

        # 3. Orphaned = provisioned but not referenced; never remove IPK (id=0).
        orphaned = all_keyset_ids - referenced_ids - {0}
        if not orphaned:
            return 0

        removed = 0
        for kid in orphaned:
            try:
                await self._chip_device_controller.send_command(
                    node_id,
                    0,  # GroupKeyManagement is always on endpoint 0
                    Clusters.GroupKeyManagement.Commands.KeySetRemove(
                        groupKeySetID=kid
                    ),
                    timed_request_timeout_ms=5000,
                )
                removed += 1
                # Remove from controller tracker so it no longer shows as orphaned.
                tracked = self._known_keysets_per_node.get(node_id)
                if tracked is not None:
                    tracked.discard(kid)
                    self.server.storage.set(
                        DATA_KEY_NODE_KEYSETS, sorted(tracked), subkey=str(node_id)
                    )
                LOGGER.info("Removed orphaned keyset %s from node %s", kid, node_id)
            except Exception:  # noqa: BLE001  # pylint: disable=W0718
                LOGGER.warning(
                    "Failed to remove keyset %s from node %s",
                    kid,
                    node_id,
                    exc_info=True,
                )

        return removed

    async def _get_node_group_key_map(
        self, node_id: int
    ) -> list[Clusters.GroupKeyManagement.Structs.GroupKeyMapStruct]:
        """Read GroupKeyMap from the device (endpoint 0, fabric-scoped).

        Returns the raw list of GroupKeyMapStruct entries, or an empty list on failure.
        """
        try:
            read_result = await self._chip_device_controller.read_attribute(
                node_id=node_id,
                attributes=[(0, Clusters.GroupKeyManagement.Attributes.GroupKeyMap)],
            )
        except Exception:  # noqa: BLE001  # pylint: disable=W0718
            return []
        if read_result is None or read_result.attributes is None:
            return []
        try:
            result: list[Clusters.GroupKeyManagement.Structs.GroupKeyMapStruct] = (
                read_result.attributes[0][Clusters.GroupKeyManagement][
                    Clusters.GroupKeyManagement.Attributes.GroupKeyMap
                ]
            )
            return result
        except (KeyError, TypeError):
            return []

    async def _provision_group_keys_on_node(  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
        self,
        node_id: int,
        group_id: int,
        keyset_id: int,
        epoch_key_hex: str,
    ) -> None:
        """Provision group encryption keys on a node, reusing existing keysets where possible.

        Algorithm (follows Matter Group Key Management Cluster semantics):

        1. Read the device's current GroupKeyMap (fabric-scoped).
        2. If group_id is already bound to our keyset_id AND the controller tracker
           confirms the keyset was actually written → fully provisioned, return early.
           (GroupKeyMap alone is NOT sufficient — the binding can outlive the keyset
           itself, e.g. after a device reset or silent KeySetWrite failure.)
        3. If the controller tracker confirms the keyset was written AND it is referenced
           by any current GroupKeyMap entry → keyset is installed; skip KeySetWrite and
           only update the GroupKeyMap binding.
        4. Otherwise write the keyset via KeySetWrite, then update GroupKeyMap.
        5. On ResourceExhausted (0x89):
           a. Run _cleanup_unused_keysets_on_node to remove orphaned keysets.
           b. Re-read device state and retry KeySetWrite if any slot was freed.
           c. If still full, find a keyset that is (a) referenced in GroupKeyMap and
              (b) tracked by the controller.  Reuse it.  Raises InvalidArguments if
              no reusable keyset can be found.
        """
        # 1. Read current device GroupKeyMap.
        entries = await self._get_node_group_key_map(node_id)
        existing_bindings: dict[int, int] = {
            e.groupId: e.groupKeySetID for e in entries
        }
        device_keyset_ids: set[int] = set(existing_bindings.values())
        tracked_keysets: set[int] = set(
            self._known_keysets_per_node.get(node_id, set())
        )

        # 2. Fully provisioned: binding exists AND tracker confirms KeySetWrite was sent.
        #    GroupKeyMap binding alone is NOT proof — the keyset can be lost while the
        #    binding remains (device reset, firmware update, silent write failure).
        if (
            existing_bindings.get(group_id) == keyset_id
            and keyset_id in tracked_keysets
        ):
            LOGGER.debug(
                "Group %s already provisioned on node %s with keyset_id %s",
                group_id,
                node_id,
                keyset_id,
            )
            return

        if (
            existing_bindings.get(group_id) == keyset_id
            and keyset_id not in tracked_keysets
        ):
            LOGGER.info(
                "GroupKeyMap binding exists for group %s on node %s (keyset_id=%s) "
                "but keyset not in controller tracker — forcing KeySetWrite to ensure "
                "device has the key",
                group_id,
                node_id,
                keyset_id,
            )
            # Fall through to (re-)write the keyset.

        # 3 & 4. Write keyset.
        #    Skip only when tracker confirms the keyset is installed AND it is referenced
        #    by a current GroupKeyMap entry (i.e., it hasn't been orphaned).
        actual_keyset_id = keyset_id
        actual_epoch_key_hex = epoch_key_hex

        if keyset_id in device_keyset_ids and keyset_id in tracked_keysets:
            # Tracker + GroupKeyMap agree: keyset is on device. Skip write.
            pass
        else:
            write_error: InteractionModelError | None = None
            try:
                await self.group_add_key_set(node_id, keyset_id, epoch_key_hex)
            except InteractionModelError as err:
                if not self._is_resource_exhausted_err(err):
                    raise
                write_error = err

            if write_error is not None:
                # 5a. ResourceExhausted — try removing orphaned keysets first.
                cleaned = await self._cleanup_unused_keysets_on_node(node_id)
                if cleaned > 0:
                    # Slots freed — retry the write.
                    try:
                        await self.group_add_key_set(node_id, keyset_id, epoch_key_hex)
                        write_error = None  # retry succeeded
                    except InteractionModelError as retry_err:
                        if not self._is_resource_exhausted_err(retry_err):
                            raise
                        write_error = retry_err

            if write_error is not None:
                # 5b. Still full after cleanup — re-read state (may have changed
                #     during cleanup) and fall back to reusing a server-managed
                #     keyset that is already installed on the device.
                entries = await self._get_node_group_key_map(node_id)
                existing_bindings = {e.groupId: e.groupKeySetID for e in entries}
                device_keyset_ids = set(existing_bindings.values())

                our_keyset_map: dict[int, str] = dict(self._group_key_store.values())
                # Reuse only keysets that: (a) server knows the epoch key for,
                # (b) are referenced in GroupKeyMap (device has them), AND
                # (c) tracker confirms they were written (not just bound).
                tracked_now = set(self._known_keysets_per_node.get(node_id, set()))
                reusable = set(our_keyset_map.keys()) & device_keyset_ids & tracked_now
                if not reusable:
                    raise InvalidArguments(
                        f"Cannot provision group {group_id} on node {node_id}: "
                        "device keyset table is full and no server-managed keyset "
                        "is installed on this device. Remove unused group memberships "
                        "or keysets on the device before adding more groups."
                    ) from write_error

                # Pick the lowest reusable keyset_id (stable, deterministic).
                actual_keyset_id = min(reusable)
                actual_epoch_key_hex = our_keyset_map[actual_keyset_id]
                LOGGER.warning(
                    "Node %s keyset table full — reusing keyset_id %s for group %s",
                    node_id,
                    actual_keyset_id,
                    group_id,
                )
                # We confirmed this keyset is on the device — record it in the tracker.
                self._record_keyset_on_node(node_id, actual_keyset_id)

                # Persist the remapped keyset so future provisioning uses the same one.
                if self._group_key_store.get(group_id) != (
                    actual_keyset_id,
                    actual_epoch_key_hex,
                ):
                    self._group_key_store[group_id] = (
                        actual_keyset_id,
                        actual_epoch_key_hex,
                    )
                    self.server.storage.set(
                        DATA_KEY_GROUP_KEYS,
                        {
                            "keyset_id": actual_keyset_id,
                            "epoch_key_hex": actual_epoch_key_hex,
                        },
                        subkey=str(group_id),
                    )
                    self._inject_controller_group_keys(
                        group_id, actual_keyset_id, actual_epoch_key_hex
                    )

        # Update GroupKeyMap: bind group_id → actual_keyset_id.
        # Re-read first to get the freshest view (keyset write may have triggered changes).
        latest_entries = await self._get_node_group_key_map(node_id)
        new_map = [m for m in latest_entries if m.groupId != group_id]
        new_map.append(
            Clusters.GroupKeyManagement.Structs.GroupKeyMapStruct(
                groupId=group_id,
                groupKeySetID=actual_keyset_id,
                fabricIndex=0,  # SDK fills this in
            )
        )
        await self._chip_device_controller.write_attribute(
            node_id=node_id,
            attributes=[
                (0, Clusters.GroupKeyManagement.Attributes.GroupKeyMap(new_map))
            ],
            timed_request_timeout_ms=5000,
        )
        LOGGER.info(
            "Provisioned node %s: group %s → keyset_id %s",
            node_id,
            group_id,
            actual_keyset_id,
        )

    @staticmethod
    def _is_resource_exhausted_err(err: InteractionModelError) -> bool:
        """Return True if the error is a Matter ResourceExhausted (status 0x89)."""
        try:
            return int(err.status) == 0x89
        except (AttributeError, TypeError, ValueError):
            return "ResourceExhausted" in str(err)

    @api_command(APICommand.GROUP_REMOVE)
    async def group_remove(self, node_id: int, endpoint: int, group_id: int) -> None:
        """Remove node from a group, then clean up any orphaned keysets.

        Matter note: RemoveGroup removes the group membership entry but does NOT
        remove the associated keyset.  We call _cleanup_unused_keysets_on_node
        afterward so keyset slots are reclaimed for future use.
        """
        await self._chip_device_controller.send_command(
            node_id,
            endpoint,
            Clusters.Groups.Commands.RemoveGroup(groupID=group_id),
        )
        await self._cleanup_unused_keysets_on_node(node_id)
        # Remove node from the provisioned-nodes tracker for this group.
        provisioned = self._group_provisioned_nodes.get(group_id)
        if provisioned and node_id in provisioned:
            provisioned.discard(node_id)
            self.server.storage.set(
                DATA_KEY_GROUP_NODES, sorted(provisioned), subkey=str(group_id)
            )

    @api_command(APICommand.GROUP_REMOVE_ALL)
    async def group_remove_all(self, node_id: int, endpoint: int) -> None:
        """Remove all groups from a node endpoint, then clean up all orphaned keysets.

        Matter note: RemoveAllGroups clears the group table but does NOT remove
        keysets.  Without the cleanup step, repeated add/remove cycles would fill
        the device's fixed keyset table (typically 3 slots) and cause
        ResourceExhausted on the next group_add.
        """
        await self._chip_device_controller.send_command(
            node_id,
            endpoint,
            Clusters.Groups.Commands.RemoveAllGroups(),
        )
        await self._cleanup_unused_keysets_on_node(node_id)
        # Remove node from provisioned-nodes tracker for every group it was in.
        changed_groups = [
            gid
            for gid, nodes in self._group_provisioned_nodes.items()
            if node_id in nodes
        ]
        for gid in changed_groups:
            self._group_provisioned_nodes[gid].discard(node_id)
            self.server.storage.set(
                DATA_KEY_GROUP_NODES,
                sorted(self._group_provisioned_nodes[gid]),
                subkey=str(gid),
            )

    @api_command(APICommand.GROUP_LIST)
    async def group_list(self, node_id: int, endpoint: int) -> GroupListResult:
        """Return all groups an endpoint belongs to, with names and remaining capacity.

        Calls GetGroupMembership (for IDs + remaining capacity) and ViewGroup (for
        each name).  The device is queried live — no server-side cache is used.
        """
        group_ids, remaining_cap = await self._get_group_membership_and_capacity(
            node_id, endpoint
        )

        groups: list[MatterGroupInfo] = []
        for gid in group_ids:
            name: str | None = None
            try:
                view_resp = await self._chip_device_controller.send_command(
                    node_id,
                    endpoint,
                    Clusters.Groups.Commands.ViewGroup(groupID=gid),
                )
                # status 0 = SUCCESS in the Groups cluster
                if int(view_resp.status) == 0:
                    name = view_resp.groupName or None
            except Exception:  # noqa: BLE001, S110  # pylint: disable=W0718
                pass  # name stays None if ViewGroup fails — not fatal
            groups.append(MatterGroupInfo(group_id=gid, group_name=name))

        return GroupListResult(
            node_id=node_id,
            endpoint=endpoint,
            remaining_capacity=remaining_cap,
            groups=groups,
        )

    @api_command(APICommand.GROUP_GET_MEMBERSHIP)
    async def group_get_membership(self, node_id: int, endpoint: int) -> list[int]:
        """Get group membership of a node."""
        read_result = await self._chip_device_controller.send_command(
            node_id,
            endpoint,
            Clusters.Groups.Commands.GetGroupMembership([]),
        )
        return cast(list[int], read_result.groupList)

    @api_command(APICommand.GROUP_DEBUG_INFO)
    async def group_debug_info(self, node_id: int) -> dict[str, Any]:
        """Return raw group key state for a node — useful for diagnosing groupcast issues.

        Reports the device's GroupKeyMap (live read), the controller-tracked keysets
        for this node, and which keysets the controller considers orphaned.
        """
        key_map = await self._get_node_group_key_map(node_id)
        referenced_ids = {e.groupKeySetID for e in key_map}
        known = set(self._known_keysets_per_node.get(node_id, set()))
        orphaned = known - referenced_ids - {0}
        return {
            "node_id": node_id,
            "group_key_map": [
                {"group_id": e.groupId, "keyset_id": e.groupKeySetID} for e in key_map
            ],
            "controller_tracked_keysets": sorted(known),
            "inferred_orphaned_keysets": sorted(orphaned),
            "group_key_store_entries": [
                {"group_id": gid, "keyset_id": kid}
                for gid, (kid, _) in self._group_key_store.items()
            ],
            "provisioned_nodes_for_group": {
                str(gid): sorted(nodes)
                for gid, nodes in self._group_provisioned_nodes.items()
                if nodes
            },
        }

    @staticmethod
    def _derive_group_encryption_key(
        epoch_key: bytes, compressed_fabric_id: int
    ) -> bytes:
        """Derive the group operational encryption key from an epoch key.

        Per Matter spec section 4.7.2.1:
          GCK = HKDF-SHA256(InputKey=epoch_key, Salt=CompressedFabricId, Info="GroupKey v1.0")
        """
        fabric_id_bytes = compressed_fabric_id.to_bytes(8, "big")
        return HKDF(
            algorithm=SHA256(),
            length=16,
            salt=fabric_id_bytes,
            info=b"GroupKey v1.0",
        ).derive(epoch_key)

    @staticmethod
    def _derive_group_session_id(encryption_key: bytes) -> int:
        """Derive the group session ID (key hash) from the encryption key.

        Per Matter spec:
          GKH = HKDF-SHA256(InputKey=encryption_key, Salt=zeros32, Info="GroupKeyHash", Length=2)
        """
        hash_bytes = HKDF(
            algorithm=SHA256(),
            length=2,
            salt=None,  # None → 32 zero bytes per RFC 5869 (matches C++ empty-salt behaviour)
            info=b"GroupKeyHash",
        ).derive(encryption_key)
        return int.from_bytes(hash_bytes, "big")

    def _inject_controller_group_keys(
        self, group_id: int, keyset_id: int, epoch_key_hex: str
    ) -> None:
        """Inject group keyset and key-map into the controller's internal KVS.

        The CHIP SDK's GroupDataProviderImpl resolves group encryption keys by
        traversing a linked list stored in the KVS (chip.json).  Because the
        Python SDK does not expose an API to add arbitrary group keys, we write
        the TLV entries directly.

        The SDK stores *derived* GroupOperationalCredentials (not raw epoch keys):
          encryption_key = HKDF-SHA256(epoch_key, CompressedFabricId, "GroupKey v1.0")
          session_id     = first 2 bytes of HKDF-SHA256(encryption_key, zeros32, "GroupKeyHash")

        Only the KeyMap and KeySet entries are written here — GroupInfo (group
        name/membership list inside the controller) is not required for
        SendGroupCommand and is deliberately omitted to keep this layer thin.
        """
        # pylint: disable=too-many-locals,protected-access,broad-exception-caught
        try:
            storage = self.server.stack._chip_stack._persistentStorage
            fabric_idx = (
                self._chip_device_controller._chip_controller.GetFabricIndexInternal()
            )
            invalid_id = 0xFFFF  # kInvalidKeysetId

            epoch_key = bytes.fromhex(epoch_key_hex)
            compressed_fabric_id = self._compressed_fabric_id or 0
            encryption_key = self._derive_group_encryption_key(
                epoch_key, compressed_fabric_id
            )
            session_id = self._derive_group_session_id(encryption_key)
            zeroed_key = bytes(16)

            # --- Read current FabricData ---
            fabric_data_name = f"f/{fabric_idx:x}/g"
            fabric_data_raw = storage.GetSdkKey(fabric_data_name)
            if fabric_data_raw is None:
                fabric_data = {
                    1: tlv_uint(0),  # first_group
                    2: tlv_uint(0),  # group_count
                    3: tlv_uint(0),  # first_map
                    4: tlv_uint(0),  # map_count
                    5: tlv_uint(invalid_id),  # first_keyset
                    6: tlv_uint(0),  # keyset_count
                    7: tlv_uint(0),  # next fabric index
                }
            else:
                fabric_data = TLVReader(fabric_data_raw).get()["Any"]

            old_first_map = fabric_data.get(3, 0)
            old_map_count = fabric_data.get(4, 0)
            old_first_keyset = fabric_data.get(5, invalid_id)
            old_keyset_count = fabric_data.get(6, 0)

            # --- Write KeySet ---
            # IMPORTANT: array must have EXACTLY 3 items (kEpochKeysMax).
            # Tag 6 = DERIVED encryption key; tag 5 = DERIVED session ID.
            keyset_key_name = f"f/{fabric_idx:x}/k/{keyset_id:x}"
            writer = TLVWriter()
            writer.put(
                None,
                {
                    1: tlv_uint(1),  # policy: kCacheAndSync
                    2: tlv_uint(1),  # keys_count (1 active epoch key)
                    3: [
                        {4: tlv_uint(0), 5: tlv_uint(session_id), 6: encryption_key},
                        {4: tlv_uint(0), 5: tlv_uint(0), 6: zeroed_key},
                        {4: tlv_uint(0), 5: tlv_uint(0), 6: zeroed_key},
                    ],
                    7: tlv_uint(old_first_keyset),
                },
            )
            storage.SetSdkKey(keyset_key_name, writer.encoding)
            fabric_data[5] = tlv_uint(keyset_id)
            fabric_data[6] = tlv_uint(old_keyset_count + 1)

            # --- Write KeyMap (group_id → keyset_id) ---
            map_id = secrets.randbelow(50000) + 10000
            map_key_name = f"f/{fabric_idx:x}/gk/{map_id:x}"
            writer = TLVWriter()
            writer.put(
                None,
                {
                    1: tlv_uint(group_id),
                    2: tlv_uint(keyset_id),
                    3: tlv_uint(old_first_map),
                },
            )
            storage.SetSdkKey(map_key_name, writer.encoding)
            fabric_data[3] = tlv_uint(map_id)
            fabric_data[4] = tlv_uint(old_map_count + 1)

            # --- Save updated FabricData ---
            writer = TLVWriter()
            writer.put(None, fabric_data)
            storage.SetSdkKey(fabric_data_name, writer.encoding)

            LOGGER.info(
                "Injected controller keys for group %s (keyset_id=%s)",
                group_id,
                keyset_id,
            )
        except Exception as err:  # noqa: BLE001
            LOGGER.error(
                "Failed to inject controller group keys for group %s: %s", group_id, err
            )

    async def _endpoint_supports_groups(self, node_id: int, endpoint_id: int) -> bool:
        """Return True if the endpoint advertises Groups cluster (id=4) in Descriptor.ServerList."""
        try:
            read_result = await self._chip_device_controller.read_attribute(
                node_id=node_id,
                attributes=[(endpoint_id, Clusters.Descriptor.Attributes.ServerList)],
            )
        except Exception:  # noqa: BLE001  # pylint: disable=W0718
            return False
        if read_result is None:
            return False
        try:
            server_list = read_result.attributes[endpoint_id][Clusters.Descriptor][
                Clusters.Descriptor.Attributes.ServerList
            ]
            return Clusters.Groups.id in server_list
        except (KeyError, TypeError):
            return False

    async def _ensure_keyset_on_node(
        self, node_id: int, keyset_id: int, epoch_key_hex: str
    ) -> None:
        """Unconditionally write the keyset to the node via KeySetWrite.

        KeySetWrite is safe to call even when the keyset already exists on the
        device — the device will overwrite the entry in-place, preserving the
        same encryption material.  This eliminates the need to guess device
        state from controller-side trackers (_known_keysets_per_node), which
        can drift after a device reboot, firmware update, or factory reset.

        Any failure is logged as a warning.  The caller must still attempt the
        groupcast so that reachable nodes are not penalised for one node being
        offline.
        """
        try:
            await self.group_add_key_set(node_id, keyset_id, epoch_key_hex)
        except Exception as err:  # noqa: BLE001  # pylint: disable=W0718
            LOGGER.warning(
                "Failed to ensure keyset %s on node %s before groupcast: %s. "
                "Groupcast to this node may be silently dropped.",
                keyset_id,
                node_id,
                err,
            )

    @api_command(APICommand.GROUP_SEND_COMMAND)
    async def send_group_command(
        self,
        group_id: int,
        cluster_id: int,
        command_name: str,
        payload: dict[str, Any],
    ) -> None:
        """Send a command to a group using Matter multicast (groupcast).

        The CHIP controller sends a single multicast frame addressed to the
        group ID — no per-node unicast loop is performed.  The controller must
        have the group's encryption keys in its GroupDataProvider, which are
        injected automatically when a group is first created via group_add.
        """
        cluster_cls: Cluster = ALL_CLUSTERS[cluster_id]
        command_cls = getattr(cluster_cls.Commands, command_name)
        command = dataclass_from_dict(command_cls, payload, allow_sdk_types=True)

        # Pre-send: enforce keyset presence on every provisioned node.
        # We call KeySetWrite unconditionally — do NOT skip based on the
        # controller-side tracker (_known_keysets_per_node).  The tracker is
        # a controller-side assumption and can drift after a device reboot,
        # firmware update, or factory reset.  KeySetWrite is idempotent: the
        # device overwrites the entry in-place if the keyset already exists,
        # so calling it again is always safe.
        if group_id in self._group_key_store:
            keyset_id_check, epoch_key_hex_check = self._group_key_store[group_id]
            for nid in set(self._group_provisioned_nodes.get(group_id, set())):
                await self._ensure_keyset_on_node(
                    nid, keyset_id_check, epoch_key_hex_check
                )

        try:
            await self._chip_device_controller.send_group_command(group_id, command)
        except ChipStackError as err:
            if err.err == 0xAC and group_id in self._group_key_store:
                # 0xAC is a CONTROLLER-SIDE error: the CHIP SDK cannot find the
                # encryption key in its local GroupDataProvider (e.g. after a server
                # restart before the KVS was re-populated).
                # Fix: re-inject into the controller's local SDK storage and retry.
                # NOTE: this fixes the controller side only. If the device is also
                # missing the keyset (e.g. after a factory reset), the multicast will
                # be sent successfully from the controller's perspective but silently
                # dropped by the device. In that case, call group_add again on each
                # affected node to re-run KeySetWrite on the device.
                keyset_id, epoch_key_hex = self._group_key_store[group_id]
                LOGGER.info(
                    "Controller lost keys for group %s (0xAC) — re-injecting into "
                    "local SDK storage and retrying. If groupcast still has no effect, "
                    "the device may be missing the keyset — call group_add to re-provision.",
                    group_id,
                )
                self._inject_controller_group_keys(group_id, keyset_id, epoch_key_hex)
                await self._chip_device_controller.send_group_command(group_id, command)
                return
            if err.err == 0xAC:
                raise InvalidArguments(
                    f"Group command failed (0xAC) for group_id {group_id}: "
                    "no encryption keys found. Call group_add first to provision "
                    "the controller and nodes with the required keys."
                ) from err
            raise

    @api_command(APICommand.GET_FABRICS)
    async def get_fabrics(self, node_id: int) -> list[MatterFabricInfo]:
        """Get fabrics of a node."""
        read_response = await self._chip_device_controller.read_attribute(
            node_id,
            [(0, Clusters.OperationalCredentials.Attributes.Fabrics)],
            fabric_filtered=False,
        )
        if read_response is None:
            return []

        fabrics = read_response.attributes[0][Clusters.OperationalCredentials][
            Clusters.OperationalCredentials.Attributes.Fabrics
        ]
        return [
            MatterFabricInfo(
                fabric_index=f.fabricIndex,
                root_public_key=f.rootPublicKey,
                vendor_id=f.vendorId,
                fabric_id=f.fabricId,
                node_id=f.nodeId,
                label=f.label,
            )
            for f in fabrics
        ]

    @api_command(APICommand.REMOVE_FABRIC)
    async def remove_fabric(self, node_id: int, fabric_index: int) -> None:
        """Remove a fabric from a node."""
        await self._chip_device_controller.send_command(
            node_id,
            0,
            Clusters.OperationalCredentials.Commands.RemoveFabric(
                fabricIndex=fabric_index
            ),
        )

    @api_command(APICommand.UPDATE_FABRIC_LABEL)
    async def update_fabric_label(self, node_id: int, label: str) -> None:
        """Update fabric label of a node."""
        await self._chip_device_controller.send_command(
            node_id,
            0,
            Clusters.OperationalCredentials.Commands.UpdateFabricLabel(label=label),
        )

    @api_command(APICommand.GROUP_ADD_KEY_SET)
    async def group_add_key_set(
        self,
        node_id: int,
        keyset_id: int,
        key_hex: str = "0102030405060708090a0b0c0d0e0f10",
    ) -> None:
        """Add a group key set to a node."""
        key = bytes.fromhex(key_hex)
        await self._chip_device_controller.send_command(
            node_id=node_id,
            endpoint_id=0,
            command=Clusters.GroupKeyManagement.Commands.KeySetWrite(
                groupKeySet=Clusters.GroupKeyManagement.Structs.GroupKeySetStruct(
                    groupKeySetID=keyset_id,
                    groupKeySecurityPolicy=Clusters.GroupKeyManagement.Enums.GroupKeySecurityPolicyEnum.kTrustFirst,
                    epochKey0=key,
                    epochStartTime0=1,
                )
            ),
            timed_request_timeout_ms=5000,
        )
        # Track that this keyset is now installed on the node so we can clean it up
        # later even when the device does not support GroupKeyTable (e.g. Tapo).
        tracked = self._known_keysets_per_node.setdefault(node_id, set())
        tracked.add(keyset_id)
        self.server.storage.set(
            DATA_KEY_NODE_KEYSETS, sorted(tracked), subkey=str(node_id)
        )

    @api_command(APICommand.GROUP_BIND_KEY_SET)
    async def group_bind_key_set(
        self,
        node_id: int,
        group_id: int,
        keyset_id: int,
    ) -> None:
        """Bind a group ID to a keyset ID on a node."""
        # Get existing mappings first
        read_result = await self._chip_device_controller.read_attribute(
            node_id=node_id,
            attributes=[(0, Clusters.GroupKeyManagement.Attributes.GroupKeyMap)],
        )
        if read_result is None or read_result.attributes is None:
            return
        current_map: list[Clusters.GroupKeyManagement.Structs.GroupKeyMapStruct] = (
            read_result.attributes[0][Clusters.GroupKeyManagement][
                Clusters.GroupKeyManagement.Attributes.GroupKeyMap
            ]
        )

        # Add or update mapping
        new_map = [m for m in current_map if m.groupId != group_id]
        new_map.append(
            Clusters.GroupKeyManagement.Structs.GroupKeyMapStruct(
                groupId=group_id,
                groupKeySetID=keyset_id,
                fabricIndex=0,  # SDK will fill this in
            )
        )

        await self._chip_device_controller.write_attribute(
            node_id=node_id,
            attributes=[
                (
                    0,
                    Clusters.GroupKeyManagement.Attributes.GroupKeyMap(new_map),
                )
            ],
            timed_request_timeout_ms=5000,
        )

    @api_command(APICommand.INIT_GROUP_TESTING_DATA)
    async def init_group_testing_data(self) -> None:
        """Populate the controller's GroupDataProvider with known test group info and keys."""
        await self._chip_device_controller.init_group_testing_data()

    @api_command(APICommand.PING_NODE)
    async def ping_node(self, node_id: int, attempts: int = 1) -> NodePingResult:
        """Ping node on the currently known IP-address(es)."""
        result: NodePingResult = {}
        if node_id >= TEST_NODE_START:
            return {"0.0.0.0": True, "0000:1111:2222:3333:4444": True}
        node = self._nodes.get(node_id)
        if node is None:
            raise NodeNotExists(
                f"Node {node_id} does not exist or is not yet interviewed"
            )
        node_logger = self.get_node_logger(LOGGER, node_id)

        battery_powered = (
            node.attributes.get(ROUTING_ROLE_ATTRIBUTE_PATH, 0)
            == Clusters.ThreadNetworkDiagnostics.Enums.RoutingRoleEnum.kSleepyEndDevice
        )

        async def _do_ping(ip_address: str) -> None:
            """Ping IP and add to result."""
            timeout = (
                NODE_PING_TIMEOUT_BATTERY_POWERED
                if battery_powered
                else NODE_PING_TIMEOUT
            )
            if "%" in ip_address:
                # ip address contains an interface index
                clean_ip, interface_idx = ip_address.split("%", 1)
                node_logger.debug(
                    "Pinging address %s (using interface %s)", clean_ip, interface_idx
                )
            else:
                node_logger.debug("Pinging address %s", ip_address)
            result[ip_address] = await ping_ip(ip_address, timeout, attempts=attempts)

        ip_addresses = await self._get_node_ip_addresses(node_id, prefer_cache=False)
        tasks = [_do_ping(x) for x in ip_addresses]
        # TODO: replace this gather with a taskgroup once we bump our py version
        await asyncio.gather(*tasks)

        # retrieve the currently connected/used address which is used
        # by the sdk for communicating with the device
        if sdk_result := await self._chip_device_controller.get_address_and_port(
            node_id
        ):
            active_address = sdk_result[0]
            node_logger.info(
                "The SDK is communicating with the device using %s", active_address
            )
            if active_address not in result and node.available:
                # if the sdk is connected to a node, treat the address as pingable
                result[active_address] = True

        return result

    async def _get_node_ip_addresses(
        self, node_id: int, prefer_cache: bool = False
    ) -> list[str]:
        """Get the IP addresses of a node."""
        cached_info = self._last_known_ip_addresses.get(node_id, [])
        if prefer_cache and cached_info:
            return cached_info
        node = self._nodes.get(node_id)
        if node is None:
            raise NodeNotExists(
                f"Node {node_id} does not exist or is not yet interviewed"
            )
        node_logger = self.get_node_logger(LOGGER, node_id)
        # query mdns for all IP's
        # ensure both fabric id and node id have 16 characters (prefix with zero's)
        mdns_name = f"{self.compressed_fabric_id:0{16}X}-{node_id:0{16}X}.{MDNS_TYPE_OPERATIONAL_NODE}"
        info = AsyncServiceInfo(MDNS_TYPE_OPERATIONAL_NODE, mdns_name)
        if TYPE_CHECKING:
            assert self._aiozc is not None
        if not await info.async_request(self._aiozc.zeroconf, 3000):
            node_logger.info(
                "Node could not be discovered on the network, returning cached IP's"
            )
            return cached_info
        ip_addresses = info.parsed_scoped_addresses(IPVersion.All)
        # cache this info for later use
        self._last_known_ip_addresses[node_id] = ip_addresses
        return ip_addresses

    @api_command(APICommand.GET_NODE_IP_ADDRESSES)
    async def get_node_ip_addresses(
        self,
        node_id: int,
        prefer_cache: bool = False,
        scoped: bool = False,
    ) -> list[str]:
        """Return the currently known (scoped) IP-address(es)."""
        ip_addresses = await self._get_node_ip_addresses(node_id, prefer_cache)
        return ip_addresses if scoped else [x.split("%")[0] for x in ip_addresses]

    @api_command(APICommand.IMPORT_TEST_NODE)
    async def import_test_node(self, dump: str) -> None:
        """Import test node(s) from a HA or Matter server diagnostics dump."""
        try:
            dump_data = cast(dict, json_loads(dump))
        except JSON_DECODE_EXCEPTIONS as err:
            raise InvalidArguments("Invalid json") from err
        # the dump format we accept here is a Home Assistant diagnostics file
        # dump can either be a single dump or a full dump with multiple nodes
        dump_nodes: list[dict[str, Any]]
        if "node" in dump_data["data"]:
            dump_nodes = [dump_data["data"]["node"]]
        else:
            dump_nodes = dump_data["data"]["server"]["nodes"]
        # node ids > 900000 are reserved for test nodes
        if self._nodes:
            next_test_node_id = max(*(x for x in self._nodes), TEST_NODE_START) + 1
        else:
            # an empty self._nodes dict evaluates to false so we set the first
            # test node id to TEST_NODE_START
            next_test_node_id = TEST_NODE_START
        for node_dict in dump_nodes:
            node = dataclass_from_dict(MatterNodeData, node_dict, strict=True)
            node.node_id = next_test_node_id
            next_test_node_id += 1
            self._nodes[node.node_id] = node
            self.server.signal_event(EventType.NODE_ADDED, node)

    @api_command(APICommand.CHECK_NODE_UPDATE)
    async def check_node_update(self, node_id: int) -> MatterSoftwareVersion | None:
        """
        Check if there is an update for a particular node.

        Reads the current software version and checks the DCL if there is an update
        available. If there is an update available, the command returns the version
        information of the latest update available.
        """

        update_source, update = await self._check_node_update(node_id)
        if update_source is None or update is None:
            return None

        if not all(
            key in update
            for key in [
                "vid",
                "pid",
                "softwareVersion",
                "softwareVersionString",
                "minApplicableSoftwareVersion",
                "maxApplicableSoftwareVersion",
            ]
        ):
            raise UpdateCheckError("Invalid update data")

        return MatterSoftwareVersion(
            vid=update["vid"],
            pid=update["pid"],
            software_version=update["softwareVersion"],
            software_version_string=update["softwareVersionString"],
            firmware_information=update.get("firmwareInformation", None),
            min_applicable_software_version=update["minApplicableSoftwareVersion"],
            max_applicable_software_version=update["maxApplicableSoftwareVersion"],
            release_notes_url=update.get("releaseNotesUrl", None),
            update_source=update_source,
        )

    @api_command(APICommand.UPDATE_NODE)
    async def update_node(self, node_id: int, software_version: int | str) -> None:
        """
        Update a node to a new software version.

        This command checks if the requested software version is indeed still available
        and if so, it will start the update process. The update process will be handled
        by the built-in OTA provider. The OTA provider will download the update and
        notify the node about the new update.
        """

        node_logger = self.get_node_logger(LOGGER, node_id)
        node_logger.info("Update to software version %r", software_version)

        _, update = await self._check_node_update(node_id, software_version)
        if update is None:
            raise UpdateCheckError(
                f"Software version {software_version} is not available for node {node_id}."
            )

        # Add update to the OTA provider
        ota_provider = ExternalOtaProvider(
            self.server.vendor_id,
            self._ota_provider_dir,
            self._ota_provider_dir / f"{node_id}",
        )

        await ota_provider.initialize()

        node_logger.info("Downloading update from '%s'", update["otaUrl"])
        await ota_provider.fetch_update(update)

        self._attribute_update_callbacks.setdefault(node_id, []).append(
            ota_provider.check_update_state
        )

        try:
            if node_id in self._nodes_in_ota:
                raise UpdateError(
                    f"Node {node_id} is already in the process of updating."
                )

            self._nodes_in_ota.add(node_id)

            # Make sure any previous instances get stopped
            node_logger.info("Starting update using OTA Provider.")
            await ota_provider.start_update(
                self._chip_device_controller,
                node_id,
            )
        finally:
            self._attribute_update_callbacks[node_id].remove(
                ota_provider.check_update_state
            )
            self._nodes_in_ota.remove(node_id)

    async def _check_node_update(
        self,
        node_id: int,
        requested_software_version: int | str | None = None,
    ) -> tuple[UpdateSource, dict] | tuple[None, None]:
        node_logger = self.get_node_logger(LOGGER, node_id)
        node = self._nodes[node_id]

        node_logger.debug("Check for updates.")
        vid = cast(int, node.attributes.get(BASIC_INFORMATION_VENDOR_ID_ATTRIBUTE_PATH))
        pid = cast(
            int, node.attributes.get(BASIC_INFORMATION_PRODUCT_ID_ATTRIBUTE_PATH)
        )
        software_version = cast(
            int, node.attributes.get(BASIC_INFORMATION_SOFTWARE_VERSION_ATTRIBUTE_PATH)
        )
        software_version_string = node.attributes.get(
            BASIC_INFORMATION_SOFTWARE_VERSION_STRING_ATTRIBUTE_PATH
        )

        update_source, update = await check_for_update(
            node_logger, vid, pid, software_version, requested_software_version
        )
        if not update_source or not update:
            node_logger.info("No new update found.")
            return None, None

        if "otaUrl" not in update or update["otaUrl"].strip() == "":
            raise UpdateCheckError("Update found, but no OTA URL provided.")

        node_logger.info(
            "Software update found: %s (%s) from %s, current %s (%s)).",
            update["softwareVersionString"],
            update["softwareVersion"],
            update_source,
            software_version_string,
            software_version,
        )
        return update_source, update

    async def _subscribe_node(self, node_id: int) -> None:
        """
        Subscribe to all node state changes/events for an individual node.

        Note that by using the listen command at server level,
        you will receive all (subscribed) node events and attribute updates.
        """
        # pylint: disable=too-many-locals,too-many-statements
        if self._nodes.get(node_id) is None:
            raise NodeNotExists(
                f"Node {node_id} does not exist or has not been interviewed."
            )

        node_logger = self.get_node_logger(LOGGER, node_id)

        # Shutdown existing subscriptions for this node first
        await self._chip_device_controller.shutdown_subscription(node_id)

        def attribute_updated_callback(
            path: Attribute.AttributePath,
            old_value: Any,
            new_value: Any,
        ) -> None:
            node_logger.log(
                VERBOSE_LOG_LEVEL,
                "Attribute updated: %s - old value: %s - new value: %s",
                path,
                old_value,
                new_value,
            )

            # work out added/removed endpoints on bridges
            node = self._nodes[node_id]
            if node.is_bridge and str(path) == DESCRIPTOR_PARTS_LIST_ATTRIBUTE_PATH:
                endpoints_removed = set(old_value or []) - set(new_value)
                endpoints_added = set(new_value) - set(old_value or [])
                if endpoints_removed:
                    self._handle_endpoints_removed(node_id, endpoints_removed)
                if endpoints_added:
                    self._loop.create_task(
                        self._handle_endpoints_added(node_id, endpoints_added)
                    )
                return

            # work out if software version changed
            if (
                str(path) == BASIC_INFORMATION_SOFTWARE_VERSION_ATTRIBUTE_PATH
                and new_value != old_value
            ):
                # schedule a full interview of the node if the software version changed
                self._loop.create_task(self._interview_node(node_id))

            # store updated value in node attributes
            node.attributes[str(path)] = new_value

            # schedule save to persistent storage
            self._write_node_state(node_id)

            if node_id in self._attribute_update_callbacks:
                for callback in self._attribute_update_callbacks[node_id]:
                    self._loop.create_task(callback(path, old_value, new_value))

            # This callback is running in the CHIP stack thread
            self.server.signal_event(
                EventType.ATTRIBUTE_UPDATED,
                # send data as tuple[node_id, attribute_path, new_value]
                (node_id, str(path), new_value),
            )

        def attribute_updated_callback_threadsafe(
            path: Attribute.AttributePath,
            transaction: Attribute.SubscriptionTransaction,
        ) -> None:
            new_value = transaction.GetTLVAttribute(path)
            # failsafe: ignore ValueDecodeErrors
            # these are set by the SDK if parsing the value failed miserably
            if isinstance(new_value, ValueDecodeFailure):
                return

            node = self._nodes[node_id]
            old_value = node.attributes.get(str(path))

            # return early if the value did not actually change at all
            if old_value == new_value:
                return

            self._loop.call_soon_threadsafe(
                attribute_updated_callback, path, old_value, new_value
            )

        def event_callback(
            data: Attribute.EventReadResult,
            transaction: Attribute.SubscriptionTransaction,
        ) -> None:
            node_logger.log(
                VERBOSE_LOG_LEVEL,
                "Received node event: %s - transaction: %s",
                data,
                transaction,
            )
            node_event = MatterNodeEvent(
                node_id=node_id,
                endpoint_id=data.Header.EndpointId,
                cluster_id=data.Header.ClusterId,
                event_id=data.Header.EventId,
                event_number=data.Header.EventNumber,
                priority=data.Header.Priority,
                timestamp=data.Header.Timestamp,
                timestamp_type=data.Header.TimestampType,
                data=data.Data,
            )
            self.event_history.append(node_event)

            if isinstance(data.Data, Clusters.BasicInformation.Events.ShutDown):
                # Force resubscription after a shutdown event. Otherwise we'd have to
                # wait for up to NODE_SUBSCRIPTION_CEILING_BATTERY_POWERED minutes for
                # the SDK to notice the device is gone.
                self._node_unavailable(node_id, True)

            self.server.signal_event(EventType.NODE_EVENT, node_event)

        def event_callback_threadsafe(
            data: Attribute.EventReadResult,
            transaction: Attribute.SubscriptionTransaction,
        ) -> None:
            self._loop.call_soon_threadsafe(event_callback, data, transaction)

        def error_callback(
            chipError: int, transaction: Attribute.SubscriptionTransaction
        ) -> None:
            # pylint: disable=unused-argument, invalid-name
            node_logger.error("Got error from node: %s", chipError)

        def resubscription_attempted(
            transaction: Attribute.SubscriptionTransaction,
            terminationError: int,
            nextResubscribeIntervalMsec: int,
        ) -> None:
            # pylint: disable=unused-argument, invalid-name
            resubscription_attempt = self._resubscription_attempt[node_id]
            node_logger.info(
                "Subscription failed with %s, resubscription attempt %s",
                str(PyChipError(code=terminationError)),
                resubscription_attempt,
            )
            self._resubscription_attempt[node_id] = resubscription_attempt + 1
            if resubscription_attempt == 0:
                self._first_resubscribe_attempt[node_id] = time.time()
            # Mark node as unavailable and signal consumers.
            # We debounce it a bit so we only mark the node unavailable
            # after some resubscription attempts.
            if resubscription_attempt >= NODE_RESUBSCRIBE_ATTEMPTS_UNAVAILABLE:
                self._node_unavailable(node_id)
            # Shutdown the subscription if we tried to resubscribe for more than 30
            # minutes (typical TTL of mDNS). We assume this device got powered off.
            # When the device gets powered on again, it typically announces itself via
            # mDNS again. The mDNS browsing code will setup the subscription again.
            if (
                time.time() - self._first_resubscribe_attempt[node_id]
                > NODE_RESUBSCRIBE_TIMEOUT_OFFLINE
            ):
                asyncio.create_task(self._node_offline(node_id))

        def resubscription_succeeded(
            transaction: Attribute.SubscriptionTransaction,
        ) -> None:
            # pylint: disable=unused-argument, invalid-name
            node_logger.info("Re-Subscription succeeded")
            self._resubscription_attempt[node_id] = 0
            self._first_resubscribe_attempt.pop(node_id, None)
            # mark node as available and signal consumers
            node = self._nodes[node_id]
            if not node.available:
                node.available = True
                self.server.signal_event(EventType.NODE_UPDATED, node)

        node_logger.info("Setting up attributes and events subscription.")
        # determine subscription ceiling based on routing role
        # Endpoint 0, ThreadNetworkDiagnostics Cluster, routingRole attribute
        # for WiFi devices, this cluster doesn't exist.
        node = self._nodes[node_id]
        routing_role = node.attributes.get(ROUTING_ROLE_ATTRIBUTE_PATH)
        if routing_role is None:
            interval_ceiling = NODE_SUBSCRIPTION_CEILING_WIFI
        elif (
            routing_role
            == Clusters.ThreadNetworkDiagnostics.Enums.RoutingRoleEnum.kSleepyEndDevice
        ):
            interval_ceiling = NODE_SUBSCRIPTION_CEILING_BATTERY_POWERED
        else:
            interval_ceiling = NODE_SUBSCRIPTION_CEILING_THREAD
        if node.attributes.get(ICD_ATTR_LIST_ATTRIBUTE_PATH) is not None:
            # for ICD devices, the interval floor must be 0 according to the spec,
            # to prevent additional battery drainage. See Matter core spec, chapter 8.5.2.2.
            # TODO: revisit this after Matter 1.4 release (as that mighht change this again).
            interval_floor = NODE_SUBSCRIPTION_FLOOR_ICD
        else:
            interval_floor = NODE_SUBSCRIPTION_FLOOR_DEFAULT
        self._resubscription_attempt[node_id] = 0
        # set-up the actual subscription
        sub: Attribute.SubscriptionTransaction = (
            await self._chip_device_controller.read_attribute(
                node_id,
                [()],
                events=[("*", 1)],
                return_cluster_objects=False,
                report_interval=(interval_floor, interval_ceiling),
                auto_resubscribe=True,
            )
        )

        # Make sure to clear default handler which prints to stdout
        sub.SetAttributeUpdateCallback(None)
        sub.SetRawAttributeUpdateCallback(attribute_updated_callback_threadsafe)
        sub.SetEventUpdateCallback(event_callback_threadsafe)
        sub.SetErrorCallback(error_callback)
        sub.SetResubscriptionAttemptedCallback(resubscription_attempted)
        sub.SetResubscriptionSucceededCallback(resubscription_succeeded)

        node.available = True
        # update attributes with current state from read request
        tlv_attributes = sub.GetTLVAttributes()
        node.attributes.update(parse_attributes_from_read_result(tlv_attributes))

        report_interval_floor, report_interval_ceiling = (
            sub.GetReportingIntervalsSeconds()
        )
        node_logger.info(
            "Subscription succeeded with report interval [%d, %d]",
            report_interval_floor,
            report_interval_ceiling,
        )

        self.server.signal_event(EventType.NODE_UPDATED, node)

    def _get_next_node_id(self) -> int:
        """Return next node_id."""
        next_node_id = cast(int, self.server.storage.get(DATA_KEY_LAST_NODE_ID, 0)) + 1
        self.server.storage.set(DATA_KEY_LAST_NODE_ID, next_node_id, force=True)
        return next_node_id

    async def _setup_node_try_once(
        self,
        node_logger: logging.LoggerAdapter,
        node_id: int,
    ) -> None:
        """Handle set-up of subscriptions and interview (if needed) for known/discovered node."""
        node_data = self._nodes[node_id]
        is_thread_node = (
            node_data.attributes.get(ROUTING_ROLE_ATTRIBUTE_PATH) is not None
        )

        # use semaphore for thread based devices to (somewhat)
        # throttle the traffic that setup/initial subscription generates
        if is_thread_node:
            await self._thread_node_setup_throttle.acquire()

        try:
            node_logger.info("Setting-up node...")

            # try to resolve the node using the sdk first before do anything else
            try:
                await self._chip_device_controller.find_or_establish_case_session(
                    node_id=node_id
                )
            except NodeNotResolving as err:
                node_logger.warning(
                    "Setup for node failed: %s",
                    str(err) or err.__class__.__name__,
                    # log full stack trace if verbose logging is enabled
                    exc_info=err if LOGGER.isEnabledFor(VERBOSE_LOG_LEVEL) else None,
                )
                raise err

            # (re)interview node (only) if needed
            if (
                # re-interview if we dont have any node attributes (empty node)
                not node_data.attributes
                # re-interview if the data model schema has changed
                or node_data.interview_version != DATA_MODEL_SCHEMA_VERSION
            ):
                try:
                    await self._interview_node(node_id)
                except NodeInterviewFailed as err:
                    node_logger.warning(
                        "Setup for node failed: %s",
                        str(err) or err.__class__.__name__,
                        # log full stack trace if verbose logging is enabled
                        exc_info=err
                        if LOGGER.isEnabledFor(VERBOSE_LOG_LEVEL)
                        else None,
                    )
                    raise err

            # setup subscriptions for the node
            try:
                await self._subscribe_node(node_id)
            except ChipStackError as err:
                node_logger.warning(
                    "Unable to subscribe to Node: %s",
                    str(err) or err.__class__.__name__,
                    # log full stack trace if verbose logging is enabled
                    exc_info=err if LOGGER.isEnabledFor(VERBOSE_LOG_LEVEL) else None,
                )
                raise err

            # check if this node has any custom clusters that need to be polled
            if polled_attributes := check_polled_attributes(node_data):
                self._polled_attributes[node_id] = polled_attributes
                self._schedule_custom_attributes_poller()
        finally:
            if is_thread_node:
                self._thread_node_setup_throttle.release()

    async def _setup_node(self, node_id: int) -> None:
        if node_id not in self._nodes:
            raise NodeNotExists(f"Node {node_id} does not exist.")

        node_logger = self.get_node_logger(LOGGER, node_id)

        while True:
            try:
                await self._setup_node_try_once(node_logger, node_id)
                break
            except (NodeNotResolving, NodeInterviewFailed, ChipStackError):
                if (
                    time.time() - self._node_last_seen_on_mdns.get(node_id, 0)
                    > NODE_MDNS_SUBSCRIPTION_RETRY_TIMEOUT
                ):
                    # NOTE: assume the node will be picked up by mdns discovery later
                    # automatically when it becomes available again.
                    node_logger.warning(
                        "Node setup not completed after %s minutes, giving up.",
                        NODE_MDNS_SUBSCRIPTION_RETRY_TIMEOUT // 60,
                    )
                    break

            node_logger.info("Retrying node setup in 60 seconds...")
            await asyncio.sleep(60)

    def _setup_node_create_task(self, node_id: int) -> asyncio.Task | None:
        """Create a task for setting up a node with retry."""
        if node_id in self._setup_node_tasks:
            node_logger = self.get_node_logger(LOGGER, node_id)
            node_logger.debug("Setup task exists already for this Node")
            return None
        task = asyncio.create_task(self._setup_node(node_id))
        task.add_done_callback(lambda _: self._setup_node_tasks.pop(node_id, None))
        self._setup_node_tasks[node_id] = task
        return task

    def _handle_endpoints_removed(self, node_id: int, endpoints: Iterable[int]) -> None:
        """Handle callback for when bridge endpoint(s) get deleted."""
        node = self._nodes[node_id]
        for endpoint_id in endpoints:
            node.attributes = {
                key: value
                for key, value in node.attributes.items()
                if not key.startswith(f"{endpoint_id}/")
            }
            self.server.signal_event(
                EventType.ENDPOINT_REMOVED,
                {"node_id": node_id, "endpoint_id": endpoint_id},
            )
        # schedule save to persistent storage
        self._write_node_state(node_id)

    async def _handle_endpoints_added(
        self, node_id: int, endpoints: Iterable[int]
    ) -> None:
        """Handle callback for when bridge endpoint(s) get added."""
        # we simply do a full interview of the node
        await self._interview_node(node_id)
        # signal event to consumers
        for endpoint_id in endpoints:
            self.server.signal_event(
                EventType.ENDPOINT_ADDED,
                {"node_id": node_id, "endpoint_id": endpoint_id},
            )

    def _on_mdns_service_state_change(
        self,
        zeroconf: Zeroconf,  # pylint: disable=unused-argument
        service_type: str,
        name: str,
        state_change: ServiceStateChange,
    ) -> None:
        # mdns events may arrive in bursts of (duplicate) messages
        # so we debounce this with a timer handle.
        if state_change == ServiceStateChange.Removed:
            # if we have an existing timer for this name, cancel it.
            if cancel := self._mdns_event_timer.pop(name, None):
                cancel.cancel()
            if service_type == MDNS_TYPE_OPERATIONAL_NODE:
                # we're not interested in operational node removals,
                # this is already handled by the subscription logic
                return

        if name in self._mdns_event_timer:
            # We already have a timer to resolve this service, so ignore this callback.
            return

        if service_type == MDNS_TYPE_COMMISSIONABLE_NODE:
            # process the event with a debounce timer
            self._mdns_event_timer[name] = self._loop.call_later(
                0.5, self._on_mdns_commissionable_node_state, name, state_change
            )
            return

        if service_type != MDNS_TYPE_OPERATIONAL_NODE:
            return

        if not (match := RE_MDNS_SERVICE_NAME.match(name)):
            LOGGER.getChild("mdns").warning(
                "Service name doesn't match expected operational node pattern: %s", name
            )
            return

        fabric_id_hex, node_id_hex = match.groups()

        # Filter messages of other fabrics
        if int(fabric_id_hex, 16) != self.compressed_fabric_id:
            return

        # Process the event with a debounce timer
        self._mdns_event_timer[name] = self._loop.call_later(
            0.5,
            self._on_mdns_operational_node_state,
            name,
            int(node_id_hex, 16),
            state_change,
        )

    def _on_mdns_operational_node_state(
        self, name: str, node_id: int, state_change: ServiceStateChange
    ) -> None:
        """Handle a (operational) Matter node MDNS state change."""
        self._mdns_event_timer.pop(name, None)
        node_logger = self.get_node_logger(LOGGER.getChild("mdns"), node_id)

        if not (node := self._nodes.get(node_id)):
            return  # this should not happen, but guard just in case

        self._node_last_seen_on_mdns[node_id] = time.time()

        # we only treat UPDATE state changes as ADD if the node is marked as
        # unavailable to ensure we catch a node being operational
        if node.available and state_change == ServiceStateChange.Updated:
            return

        if not self._chip_device_controller.node_has_subscription(node_id):
            node_logger.info("Discovered on mDNS")
            # Setup the node - this will setup the subscriptions etc.
            self._setup_node_create_task(node_id)
        elif state_change == ServiceStateChange.Added:
            # Trigger node re-subscriptions when mDNS entry got added
            # Note: Users seem to get such mDNS messages fairly regularly, and often
            # the subscription to the device is healthy and fine. This is not a problem
            # since trigger_resubscribe_if_scheduled won't do anything in that case
            # (no resubscribe is scheduled).
            # But this does speedup the resubscription process in case the subscription
            # is already in resubscribe mode.
            node_logger.debug("Activity on mDNS, trigger resubscribe if scheduled")
            asyncio.create_task(
                self._chip_device_controller.trigger_resubscribe_if_scheduled(
                    node_id, "mDNS state change detected"
                )
            )

    def _on_mdns_commissionable_node_state(
        self, name: str, state_change: ServiceStateChange
    ) -> None:
        """Handle a (commissionable) Matter node MDNS state change."""
        self._mdns_event_timer.pop(name, None)
        logger = LOGGER.getChild("mdns")

        try:
            info = AsyncServiceInfo(MDNS_TYPE_COMMISSIONABLE_NODE, name)
        except BadTypeInNameException as ex:
            logger.debug("Ignoring record with bad type in name: %s: %s", name, ex)
            return

        async def handle_commissionable_node_added() -> None:
            if TYPE_CHECKING:
                assert self._aiozc is not None
            await info.async_request(self._aiozc.zeroconf, 3000)
            logger.debug("Discovered commissionable Matter node: %s", info)

            # Map MDNS info to CommissionableNodeData
            props = info.properties

            # convert bytes to int/str
            def get_prop(key: str, default: Any = None) -> Any:
                val = props.get(key.encode())
                if val is None:
                    return default
                return val.decode()

            node_data = CommissionableNodeData(
                instance_name=info.name.split(".")[0],
                host_name=info.server,
                port=info.port,
                long_discriminator=int(get_prop("D", 0)),
                vendor_id=int(get_prop("V", 0)),
                product_id=int(get_prop("P", 0)),
                commissioning_mode=int(get_prop("CM", 0)),
                device_type=int(get_prop("DT", 0)),
                device_name=get_prop("DN"),
                pairing_instruction=get_prop("RI"),
                pairing_hint=int(get_prop("PH", 0)),
                addresses=info.parsed_addresses(),
            )
            self.server.signal_event(EventType.DISCOVERY_UPDATED, node_data)

        if state_change == ServiceStateChange.Added:
            asyncio.create_task(handle_commissionable_node_added())
        elif state_change == ServiceStateChange.Removed:
            logger.debug("Commissionable Matter node disappeared: %s", info)
            self.server.signal_event(
                EventType.DISCOVERY_UPDATED, {"name": name, "removed": True}
            )

    def _write_node_state(self, node_id: int, force: bool = False) -> None:
        """Schedule the write of the current node state to persistent storage."""
        if node_id not in self._nodes:
            return  # guard
        if node_id >= TEST_NODE_START:
            return  # test nodes are stored in memory only
        node = self._nodes[node_id]
        self.server.storage.set(
            DATA_KEY_NODES,
            value=node,
            subkey=str(node_id),
            force=force,
        )

    def _node_unavailable(
        self, node_id: int, force_resubscription: bool = False
    ) -> None:
        """Mark node as unavailable."""
        # mark node as unavailable (if it wasn't already)
        node = self._nodes[node_id]
        if not node.available:
            return
        node.available = False
        self.server.signal_event(EventType.NODE_UPDATED, node)
        node_logger = self.get_node_logger(LOGGER, node_id)
        node_logger.info("Marked node as unavailable")
        if force_resubscription:
            # Make sure the subscriptions are expiring very soon to trigger subscription
            # resumption logic quickly. This is especially important for battery operated
            # devices so subscription resumption logic kicks in quickly.
            node_logger.info(
                "Forcing subscription timeout in %ds", NODE_RESUBSCRIBE_FORCE_TIMEOUT
            )
            asyncio.create_task(
                self._chip_device_controller.subscription_override_liveness_timeout(
                    node_id, NODE_RESUBSCRIBE_FORCE_TIMEOUT * 1000
                )
            )
            # Clear the timeout soon after the scheduled timeout above. This causes the
            # SDK to use the default liveness timeout again, which is what we want for
            # the once resumed subscription.
            self._loop.call_later(
                NODE_RESUBSCRIBE_FORCE_TIMEOUT + 1,
                lambda: asyncio.create_task(
                    self._chip_device_controller.subscription_override_liveness_timeout(
                        node_id, 0
                    )
                ),
            )

    async def _node_offline(self, node_id: int) -> None:
        """Mark node as offline."""
        # shutdown existing subscriptions
        node_logger = self.get_node_logger(LOGGER, node_id)
        node_logger.info("Node considered offline, shutdown subscription")
        await self._chip_device_controller.shutdown_subscription(node_id)

        # inform listeners for update callbacks that this subscription is now offline
        if node_id in self._attribute_update_callbacks:
            for callback in self._attribute_update_callbacks[node_id]:
                self._loop.create_task(callback(None, None, None))

        # mark node as unavailable (if it wasn't already)
        self._node_unavailable(node_id)

    async def _custom_attributes_poller(self) -> None:
        """Poll custom clusters/attributes for changes."""
        for node_id in tuple(self._polled_attributes):
            node = self._nodes[node_id]
            if not node.available:
                continue
            attribute_paths = list(self._polled_attributes[node_id])
            try:
                # try to read the attribute(s) - this will fire an event if the value changed
                await self.read_attribute(
                    node_id, attribute_paths, fabric_filtered=False
                )
            except (ChipStackError, NodeNotReady) as err:
                LOGGER.warning(
                    "Polling custom attribute(s) %s for node %s failed: %s",
                    ",".join(attribute_paths),
                    node_id,
                    str(err) or err.__class__.__name__,
                    # log full stack trace if verbose logging is enabled
                    exc_info=err if LOGGER.isEnabledFor(VERBOSE_LOG_LEVEL) else None,
                )
            # polling attributes is heavy on network traffic, so we throttle it a bit
            await asyncio.sleep(2)
        # reschedule self to run at next interval
        self._schedule_custom_attributes_poller()

    def _schedule_custom_attributes_poller(self) -> None:
        """Schedule running the custom clusters/attributes poller at X interval."""
        if existing := self._custom_attribute_poller_timer:
            existing.cancel()

        def run_custom_attributes_poller() -> None:
            self._custom_attribute_poller_timer = None
            if (existing := self._custom_attribute_poller_task) and not existing.done():
                existing.cancel()
            self._custom_attribute_poller_task = asyncio.create_task(
                self._custom_attributes_poller()
            )

        # no need to schedule the poll if we have no (more) custom attributes to poll
        if not self._polled_attributes:
            return

        self._custom_attribute_poller_timer = self._loop.call_later(
            CUSTOM_ATTRIBUTES_POLLER_INTERVAL, run_custom_attributes_poller
        )
