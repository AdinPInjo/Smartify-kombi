/**
 * Get Desired State Edge Function
 * Returns the desired configuration state for a device
 */

import { serve } from 'https://deno.land/std@0.168.0/http/server.ts'
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2'
import { corsHeaders } from '../_shared/cors.ts'
import { validateDeviceToken } from '../_shared/auth.ts'

serve(async (req) => {
  // Handle CORS preflight
  if (req.method === 'OPTIONS') {
    return new Response('ok', { headers: corsHeaders })
  }

  try {
    // Create Supabase client with service role key
    const supabase = createClient(
      Deno.env.get('SUPABASE_URL') ?? '',
      Deno.env.get('SUPABASE_SERVICE_ROLE_KEY') ?? ''
    )

    // Validate device token
    const authHeader = req.headers.get('Authorization')
    const { device_id, error: authError } = await validateDeviceToken(supabase, authHeader)

    if (authError || !device_id) {
      return new Response(
        JSON.stringify({ error: authError || 'Unauthorized' }),
        {
          status: 401,
          headers: { ...corsHeaders, 'Content-Type': 'application/json' },
        }
      )
    }

    // Get desired state from device_settings
    const { data, error } = await supabase
      .from('device_settings')
      .select('version, settings')
      .eq('device_id', device_id)
      .single()

    if (error) {
      // No settings yet - return default
      if (error.code === 'PGRST116') {
        return new Response(
          JSON.stringify({ version: 0, desired_state: {} }),
          {
            status: 200,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          }
        )
      }

      console.error('Failed to get desired state:', error)
      return new Response(
        JSON.stringify({ error: 'Failed to get desired state' }),
        {
          status: 500,
          headers: { ...corsHeaders, 'Content-Type': 'application/json' },
        }
      )
    }

    return new Response(
      JSON.stringify({
        version: data.version || 0,
        desired_state: data.settings || {},
      }),
      {
        status: 200,
        headers: { ...corsHeaders, 'Content-Type': 'application/json' },
      }
    )
  } catch (err) {
    console.error('Error in getDesiredState:', err)
    return new Response(
      JSON.stringify({ error: err.message }),
      {
        status: 400,
        headers: { ...corsHeaders, 'Content-Type': 'application/json' },
      }
    )
  }
})

