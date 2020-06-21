"""Fan support for switch entities."""
import asyncio
from collections import Counter
import itertools
import logging
from typing import Any, Callable, Iterator, List, Optional, Tuple, cast

import voluptuous as vol

from homeassistant.components import fan
from homeassistant.components.fan import (
    ATTR_SPEED,
    ATTR_SPEED_LIST,
    ATTR_OSCILLATING,
    ATTR_DIRECTION,
    PLATFORM_SCHEMA,
    SUPPORT_SET_SPEED,
    SUPPORT_OSCILLATE,
    SUPPORT_DIRECTION,
    SPEED_OFF
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_SUPPORTED_FEATURES,
    CONF_ENTITIES,
    CONF_NAME,
    STATE_ON,
    STATE_UNAVAILABLE,
)
from homeassistant.core import CALLBACK_TYPE, State, callback
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.event import async_track_state_change
from homeassistant.helpers.typing import ConfigType, HomeAssistantType

# mypy: allow-untyped-calls, allow-untyped-defs, no-check-untyped-defs
# mypy: no-check-untyped-defs

_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = "Fan SwGroupitch"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Required(CONF_ENTITIES): cv.entities_domain(fan.DOMAIN),
    }
)

SUPPORT_GROUP_FAN = (
    SUPPORT_DIRECTION
    | SUPPORT_OSCILLATE
    | SUPPORT_SET_SPEED
)

async def async_setup_platform(
    hass: HomeAssistantType,
    config: ConfigType,
    async_add_entities,
    discovery_info = None
) -> None:
    """Initialize Fan Group platform."""
    async_add_entities(
        [FanGroup(cast(str, config.get(CONF_NAME)), config[CONF_ENTITIES])], True
    )

class FanGroup(fan.FanEntity):
    """Representation of a fan group."""

    def __init__(self, name: str, entity_ids: List[str]) -> None:
        """Initialize a fan group."""
        self._name = name
        self._entity_ids = entity_ids
        self._is_on = False
        self._available = False
        self._speed: Optional[str] = None
        self._speed_list: list = []
        self._direction: Optional[str] = None
        self._oscillating = None
        self._supported_features: int = 0
        self._async_unsub_state_changed: Optional[CALLBACK_TYPE] = None

    @property
    def name(self) -> str:
        """Return the name of the entity."""
        return self._name

    @property
    def is_on(self) -> bool:
        """Return true if fan switch is on."""
        return self._is_on

    @property
    def available(self) -> bool:
        """Return true if fan switch is on."""
        return self._available

    @property
    def speed(self) -> Optional[str]:
        """Return the current speed."""
        return self._speed

    @property
    def speed_list(self) -> list:
        """Get the list of available speeds."""
        return self._speed_list        

    @property
    def current_direction(self) -> Optional[str]:
        """Return the current direction of the fan."""
        return self._direction

    @property
    def oscillating(self):
        """Return whether or not the fan is currently oscillating."""
        return self._oscillating

    @property
    def supported_features(self) -> int:
        """Flag supported features."""
        return self._supported_features

    @property
    def should_poll(self) -> bool:
        """No polling needed for a fan group."""
        return False

    @property
    def device_state_attributes(self):
        """Return the state attributes for the fan group."""
        return {ATTR_ENTITY_ID: self._entity_ids}        

    # pylint: disable=arguments-differ
    async def async_turn_on(self, speed: Optional[str] = None, **kwargs):
        """Forward the turn_on command to all fans in the fan group."""
        data = {ATTR_ENTITY_ID: self._entity_ids}

        if speed is SPEED_OFF:
            await self.async_turn_off()
        else:
            if speed is not None:
                data[ATTR_SPEED] = speed
            await self.hass.services.async_call(
                fan.DOMAIN, fan.SERVICE_TURN_ON, data, blocking=True
            )

    async def async_turn_off(self, **kwargs):
        """Forward the turn_off command to the fans in this fan group."""
        data = {ATTR_ENTITY_ID: self._entity_ids}
        await self.hass.services.async_call(
            fan.DOMAIN, fan.SERVICE_TURN_OFF, data, blocking=True
        )

    async def async_oscillate(self, oscillating: bool):
        """Oscillate the fan."""
        data = {
            ATTR_ENTITY_ID: self._entity_ids,
            ATTR_OSCILLATING: oscillating
        }

        await self.hass.services.async_call(
            fan.DOMAIN, fan.SERVICE_OSCILLATE, data, blocking=True
        )

    async def async_set_speed(self, speed: str):
        """Set the speed of the fan."""
        if speed is SPEED_OFF:
            await self.async_turn_off()
        else:
            data = {
                ATTR_ENTITY_ID: self._entity_ids,
                ATTR_SPEED: speed
            }

            await self.hass.services.async_call(
                fan.DOMAIN, fan.SERVICE_SET_SPEED, data, blocking=True
            )

    async def async_set_direction(self, direction: str):
        """Set the direction of the fan."""
        data = {
            ATTR_ENTITY_ID: self._entity_ids,
            ATTR_DIRECTION: direction
        }

        await self.hass.services.async_call(
            fan.DOMAIN, fan.SERVICE_SET_DIRECTION, data, blocking=True
        )

    async def async_update(self):
        """Query all members and determine the fan group state."""
        all_states = [self.hass.states.get(x) for x in self._entity_ids]
        states: List[State] = list(filter(None, all_states))
        on_states = [state for state in states if state.state == STATE_ON]

        self._is_on = len(on_states) > 0
        self._available = any(state.state != STATE_UNAVAILABLE for state in states)

        self._direction = _reduce_attribute(on_states, ATTR_DIRECTION)
        self._oscillating = _reduce_attribute(on_states, ATTR_OSCILLATING)

        self._speed_list = None
        all_speed_lists = list(_find_state_attributes(states, ATTR_SPEED_LIST))
        if all_speed_lists:
            self._speed_list = list(set().union(*all_speed_lists))

        self._speed = None
        all_speeds = list(_find_state_attributes(states, ATTR_SPEED))
        if all_speeds:
            speed_count = Counter(itertools.chain(all_speeds))
            self._speed = speed_count.most_common(1)[0][0]
        
        self._supported_features = 0
        for support in _find_state_attributes(states, ATTR_SUPPORTED_FEATURES):
            self._supported_features |= support
        
        self._supported_features &= SUPPORT_GROUP_FAN

    async def async_added_to_hass(self) -> None:
        """Register callbacks."""

        @callback
        def async_state_changed_listener(
            entity_id: str, old_state: State, new_state: State
        ) -> None:
            """Handle child updates."""
            self.async_schedule_update_ha_state(True)

        assert self.hass is not None
        self._async_unsub_state_changed = async_track_state_change(
            self.hass, self._entity_ids, async_state_changed_listener
        )
        await self.async_update()

    async def async_will_remove_from_hass(self):
        """Handle removal from Home Assistant."""
        if self._async_unsub_state_changed is not None:
            self._async_unsub_state_changed()
            self._async_unsub_state_changed = None

def _find_state_attributes(states: List[State], key: str) -> Iterator[Any]:
    """Find attributes with matching key from states."""
    for state in states:
        value = state.attributes.get(key)
        if value is not None:
            yield value

def _mean_int(*args):
    """Return the mean of the supplied values."""
    return int(sum(args) / len(args))

def _mean_tuple(*args):
    """Return the mean values along the columns of the supplied values."""
    return tuple(sum(x) / len(x) for x in zip(*args))

def _reduce_attribute(
    states: List[State],
    key: str,
    default: Optional[Any] = None,
    reduce: Callable[..., Any] = _mean_int,
) -> Any:
    """Find the first attribute matching key from states.
    If none are found, return default.
    """
    attrs = list(_find_state_attributes(states, key))

    if not attrs:
        return default

    if len(attrs) == 1:
        return attrs[0]

    return reduce(*attrs)