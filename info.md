# hass_fan_switch
Fan Group platform for Home Assistant

## Configuration
This component adds a fan_group platform that functions similar to the light group platform

example configuration:
```
fan:
- platform: fan_group
  name: Greatroom Fans
  entites:
  - fan.front_ceiling_fan
  - fan.rear_ceiling_fan
```

### Configuration Variables ###
<dl>
 <dt>name</dt>
 <dd>
  <i>(string)(Optional)</i><br/>The name of the fan group.
  <br/><br/>
  <i>Default value:</i><br/>Fan Group
 </dd>
 <dt>entities</dt>
 <dd>
  <i>(string | list)(Required)</i><br/>A list of entities to be included in the fan group.
 </dd>
</dl>

The supported features of all fans will be added together. For example, if you have one variable speed fan in a group of on/off only fans, the fan group will be shown with a slider.
