-- Helper function to update device settings version
CREATE OR REPLACE FUNCTION update_device_settings(
    p_device_id UUID,
    p_settings JSONB
)
RETURNS device_settings
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_result device_settings;
BEGIN
    -- Insert or update device settings, incrementing version
    INSERT INTO device_settings (device_id, version, settings, updated_at)
    VALUES (p_device_id, 1, p_settings, NOW())
    ON CONFLICT (device_id) DO UPDATE
    SET 
        version = device_settings.version + 1,
        settings = p_settings,
        updated_at = NOW()
    RETURNING * INTO v_result;
    
    RETURN v_result;
END;
$$;

-- Grant execute to authenticated users
GRANT EXECUTE ON FUNCTION update_device_settings(UUID, JSONB) TO authenticated;

COMMENT ON FUNCTION update_device_settings IS 'Update device settings and auto-increment version';

