/**
 * Acknowledge State Edge Function
 * Device confirms it has applied a configuration version
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

    // Parse acknowledgment payload
    const { applied_version, current_state } = await req.json()

    if (typeof applied_version !== 'number') {
      return new Response(
        JSON.stringify({ error: 'Invalid applied_version' }),
        {
          status: 400,
          headers: { ...corsHeaders, 'Content-Type': 'application/json' },
        }
      )
    }

    // Update device_state
    const { error: updateError } = await supabase
      .from('device_state')
      .upsert({
        device_id,
        applied_version,
        current_state: current_state || {},
        updated_at: new Date().toISOString(),
      }, {
        onConflict: 'device_id'
      })

    if (updateError) {
      console.error('Failed to update device state:', updateError)
      return new Response(
        JSON.stringify({ error: 'Failed to acknowledge state' }),
        {
          status: 500,
          headers: { ...corsHeaders, 'Content-Type': 'application/json' },
        }
      )
    }

    return new Response(
      JSON.stringify({ success: true, message: 'State acknowledged' }),
      {
        status: 200,
        headers: { ...corsHeaders, 'Content-Type': 'application/json' },
      }
    )
  } catch (err) {
    console.error('Error in ackState:', err)
    return new Response(
      JSON.stringify({ error: err.message }),
      {
        status: 400,
        headers: { ...corsHeaders, 'Content-Type': 'application/json' },
      }
    )
  }
})

