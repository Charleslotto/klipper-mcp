"""
TMC Stepper Driver Tools
Status monitoring, current control, register access, and autotune support
"""
import json
from typing import Optional, List
import config
from moonraker import get_client
from tools.security import sanitize_gcode_param


def register_tmc_tools(mcp):
    """Register TMC stepper driver tools."""

    @mcp.tool()
    async def get_tmc_status(stepper: Optional[str] = None) -> str:
        """
        Get TMC driver status for all or specific steppers.
        Shows run/hold current, phase offset, temperature (if available).
        
        Args:
            stepper: Optional stepper name (e.g., 'stepper_x', 'extruder'). If not provided, returns all.
        
        Returns:
            JSON with TMC driver status information.
        """
        client = get_client()
        
        # First get list of all printer objects
        objects_result = await client.get('/printer/objects/list')
        all_objects = objects_result.get('result', {}).get('objects', [])
        
        # Filter TMC objects
        tmc_objects = [obj for obj in all_objects if obj.startswith('tmc')]
        
        if not tmc_objects:
            return json.dumps({'error': 'No TMC drivers found'}, indent=2)
        
        # Filter by stepper name if provided
        if stepper:
            stepper_lower = stepper.lower()
            tmc_objects = [obj for obj in tmc_objects if stepper_lower in obj.lower()]
            if not tmc_objects:
                return json.dumps({'error': f'No TMC driver found for stepper: {stepper}'}, indent=2)
        
        # Build query string
        query_params = '&'.join([f'{obj.replace(" ", "%20")}' for obj in tmc_objects])
        result = await client.get(f'/printer/objects/query?{query_params}')
        status = result.get('result', {}).get('status', {})
        
        # Format the output
        tmc_status = {}
        for obj, data in status.items():
            driver_type = obj.split()[0]  # e.g., 'tmc2209'
            stepper_name = obj.split()[1] if len(obj.split()) > 1 else 'unknown'
            
            tmc_status[stepper_name] = {
                'driver': driver_type.upper(),
                'run_current': round(data.get('run_current', 0), 3),
                'hold_current': round(data.get('hold_current', 0), 3),
                'phase_offset': data.get('mcu_phase_offset'),
                'phase_offset_position': data.get('phase_offset_position'),
            }
            
            # Add temperature if available
            if data.get('temperature') is not None:
                tmc_status[stepper_name]['temperature'] = data['temperature']
            
            # Add driver status if available
            if data.get('drv_status'):
                tmc_status[stepper_name]['drv_status'] = data['drv_status']
        
        return json.dumps({
            'tmc_drivers': tmc_status,
            'count': len(tmc_status)
        }, indent=2)

    @mcp.tool()
    async def set_tmc_current(
        stepper: str,
        run_current: Optional[float] = None,
        hold_current: Optional[float] = None
    ) -> str:
        """
        Set TMC driver current for a stepper motor.
        
        Args:
            stepper: Stepper name (e.g., 'stepper_x', 'extruder')
            run_current: Run current in Amps (e.g., 0.8)
            hold_current: Hold current in Amps (e.g., 0.5). If not specified, defaults to run_current.
        
        Returns:
            Result of the current change operation.
        """
        if not config.ARMED:
            return json.dumps({'error': 'System not ARMED. TMC current changes require ARMED=true.'}, indent=2)

        if not run_current and not hold_current:
            return json.dumps({'error': 'Must specify at least run_current or hold_current'}, indent=2)

        try:
            stepper = sanitize_gcode_param(stepper, "stepper")
        except ValueError as e:
            return json.dumps({'error': str(e)}, indent=2)

        client = get_client()

        # Build the gcode command
        cmd_parts = [f'SET_TMC_CURRENT STEPPER={stepper}']
        if run_current is not None:
            cmd_parts.append(f'CURRENT={run_current}')
        if hold_current is not None:
            cmd_parts.append(f'HOLDCURRENT={hold_current}')

        gcode = ' '.join(cmd_parts)

        try:
            result = await client.run_gcode(gcode)
            if 'error' in result:
                return json.dumps({'error': result['error'], 'command': gcode}, indent=2)

            # Query the new status
            objects_result = await client.get('/printer/objects/list')
            all_objects = objects_result.get('result', {}).get('objects', [])
            tmc_obj = None
            for obj in all_objects:
                if obj.startswith('tmc') and stepper in obj:
                    tmc_obj = obj
                    break

            if tmc_obj:
                query_result = await client.get(f'/printer/objects/query?{tmc_obj.replace(" ", "%20")}')
                if 'error' in query_result:
                    # The current change itself succeeded even though this follow-up
                    # status query failed - don't report the whole call as an error.
                    return json.dumps({'success': True, 'stepper': stepper, 'command': gcode}, indent=2)
                new_status = query_result.get('result', {}).get('status', {}).get(tmc_obj, {})

                return json.dumps({
                    'success': True,
                    'stepper': stepper,
                    'command': gcode,
                    'new_settings': {
                        'run_current': round(new_status.get('run_current', 0), 3),
                        'hold_current': round(new_status.get('hold_current', 0), 3)
                    }
                }, indent=2)

            return json.dumps({'success': True, 'command': gcode}, indent=2)

        except Exception as e:
            return json.dumps({'error': str(e), 'command': gcode}, indent=2)

    @mcp.tool()
    async def dump_tmc_registers(stepper: str) -> str:
        """
        Dump TMC driver registers for diagnostics.
        Runs DUMP_TMC command and returns register values.
        
        Args:
            stepper: Stepper name (e.g., 'stepper_x', 'extruder')
        
        Returns:
            TMC register dump information.
        """
        # DUMP_TMC is a read-only diagnostic command (prints register values to the
        # console) - it does not change stepper current or any other hardware
        # state, so no ARMED gate is required here.
        try:
            stepper = sanitize_gcode_param(stepper, "stepper")
        except ValueError as e:
            return json.dumps({'error': str(e)}, indent=2)

        client = get_client()

        # Find the TMC object
        objects_result = await client.get('/printer/objects/list')
        all_objects = objects_result.get('result', {}).get('objects', [])
        tmc_obj = None
        for obj in all_objects:
            if obj.startswith('tmc') and stepper in obj:
                tmc_obj = obj
                break

        if not tmc_obj:
            return json.dumps({'error': f'No TMC driver found for: {stepper}'}, indent=2)

        driver_type = tmc_obj.split()[0].upper()

        # Run DUMP_TMC command
        gcode = f'DUMP_TMC STEPPER={stepper}'

        try:
            result = await client.run_gcode(gcode)
            if 'error' in result:
                return json.dumps({'error': result['error'], 'command': gcode}, indent=2)

            return json.dumps({
                'success': True,
                'stepper': stepper,
                'driver': driver_type,
                'command': gcode,
                'note': 'Register dump sent to console. Check Klipper console/logs for detailed register values.'
            }, indent=2)

        except Exception as e:
            return json.dumps({'error': str(e)}, indent=2)

    @mcp.tool()
    async def get_tmc_field(stepper: str, field: str) -> str:
        """
        Get a specific TMC register field value.
        
        Args:
            stepper: Stepper name (e.g., 'stepper_x')
            field: Register field name (e.g., 'pwm_scale_sum', 'sg_result')
        
        Returns:
            The field value.
        """
        # NOTE: Klipper's SET_TMC_FIELD command is write-only and requires a
        # VALUE parameter - there is no G-code command to "read" a TMC field.
        # The correct way to read a field is via the driver's printer object
        # status (e.g. `tmc2209 stepper_x`), reusing the same object-lookup
        # pattern as dump_tmc_registers/set_tmc_current above.
        try:
            stepper = sanitize_gcode_param(stepper, "stepper")
            field = sanitize_gcode_param(field, "field")
        except ValueError as e:
            return json.dumps({'error': str(e)}, indent=2)

        client = get_client()

        objects_result = await client.get('/printer/objects/list')
        all_objects = objects_result.get('result', {}).get('objects', [])
        tmc_obj = None
        for obj in all_objects:
            if obj.startswith('tmc') and stepper in obj:
                tmc_obj = obj
                break

        if not tmc_obj:
            return json.dumps({'error': f'No TMC driver found for: {stepper}'}, indent=2)

        try:
            result = await client.get(f'/printer/objects/query?{tmc_obj.replace(" ", "%20")}')
            if 'error' in result:
                return json.dumps({'error': result['error']}, indent=2)

            status = result.get('result', {}).get('status', {}).get(tmc_obj, {})
            drv_status = status.get('drv_status') if isinstance(status.get('drv_status'), dict) else {}

            if field in status:
                value = status[field]
            elif field in drv_status:
                value = drv_status[field]
            else:
                return json.dumps({
                    'error': f"Field '{field}' not found in printer object status for {tmc_obj}",
                    'available_fields': sorted(status.keys()),
                    'available_drv_status_fields': sorted(drv_status.keys())
                }, indent=2)

            return json.dumps({
                'success': True,
                'stepper': stepper,
                'field': field,
                'value': value,
                'source': tmc_obj
            }, indent=2)

        except Exception as e:
            return json.dumps({'error': str(e)}, indent=2)

    @mcp.tool()
    async def set_tmc_field(stepper: str, field: str, value: int) -> str:
        """
        Set a specific TMC register field value.
        WARNING: Incorrect values can damage hardware. Use with caution.
        
        Args:
            stepper: Stepper name (e.g., 'stepper_x')
            field: Register field name
            value: Value to set
        
        Returns:
            Result of the operation.
        """
        if not config.ARMED:
            return json.dumps({'error': 'System not ARMED. TMC field changes require ARMED=true.'}, indent=2)

        try:
            stepper = sanitize_gcode_param(stepper, "stepper")
            field = sanitize_gcode_param(field, "field")
        except ValueError as e:
            return json.dumps({'error': str(e)}, indent=2)

        client = get_client()

        gcode = f'SET_TMC_FIELD STEPPER={stepper} FIELD={field} VALUE={value}'

        try:
            result = await client.run_gcode(gcode)
            if 'error' in result:
                return json.dumps({'error': result['error'], 'command': gcode}, indent=2)

            return json.dumps({
                'success': True,
                'stepper': stepper,
                'field': field,
                'value': value,
                'command': gcode
            }, indent=2)

        except Exception as e:
            return json.dumps({'error': str(e)}, indent=2)

    @mcp.tool()
    async def get_autotune_status() -> str:
        """
        Get TMC autotune status if klipper_tmc_autotune is installed.
        Shows motor configurations and tuning parameters.
        
        Returns:
            Autotune configuration status or installation instructions.
        """
        client = get_client()
        
        # Check for autotune objects
        objects_result = await client.get('/printer/objects/list')
        all_objects = objects_result.get('result', {}).get('objects', [])
        
        autotune_objects = [obj for obj in all_objects if 'autotune' in obj.lower()]
        
        if not autotune_objects:
            return json.dumps({
                'installed': False,
                'message': 'TMC Autotune module is installed but not configured in printer.cfg',
                'configuration_required': True,
                'example_config': '''
# Add to printer.cfg for each stepper:
[autotune_tmc stepper_x]
motor: ldo-42sth48-2004mah  # Find your motor in motor_database.cfg

[autotune_tmc stepper_y]
motor: ldo-42sth48-2004mah

[autotune_tmc stepper_z]
motor: ldo-42sth48-2004ac

[autotune_tmc extruder]
motor: ldo-36sth20-1004ahg
''',
                'motor_database': 'See ~/klipper_tmc_autotune/motor_database.cfg for supported motors'
            }, indent=2)
        
        # Query autotune objects
        query_params = '&'.join([f'{obj.replace(" ", "%20")}' for obj in autotune_objects])
        result = await client.get(f'/printer/objects/query?{query_params}')
        status = result.get('result', {}).get('status', {})
        
        return json.dumps({
            'installed': True,
            'configured': True,
            'autotune_objects': list(status.keys()),
            'status': status
        }, indent=2)

    @mcp.tool()
    async def list_tmc_steppers() -> str:
        """
        List all steppers with TMC drivers and their types.
        
        Returns:
            JSON list of all TMC-equipped steppers.
        """
        client = get_client()
        
        objects_result = await client.get('/printer/objects/list')
        all_objects = objects_result.get('result', {}).get('objects', [])
        
        tmc_steppers = []
        for obj in all_objects:
            if obj.startswith('tmc'):
                parts = obj.split()
                if len(parts) >= 2:
                    tmc_steppers.append({
                        'stepper': parts[1],
                        'driver': parts[0].upper()
                    })
        
        # Check for autotune
        autotune_installed = any('autotune' in obj.lower() for obj in all_objects)
        
        return json.dumps({
            'tmc_steppers': tmc_steppers,
            'count': len(tmc_steppers),
            'autotune_configured': autotune_installed,
            'supported_commands': [
                'get_tmc_status',
                'set_tmc_current',
                'dump_tmc_registers',
                'get_tmc_field',
                'set_tmc_field',
                'get_autotune_status'
            ]
        }, indent=2)
