/**
 * Ingest Telemetry Edge Function
 * Accepts telemetry data from devices and stores in Supabase
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

    // Parse telemetry payload
    const payload = await req.json()
    const {
      temperature_c,
      water_percent,
      delta_km,
      gps_lat,
      gps_lon,
      ts,
    } = payload

    // Insert telemetry
    const { error: telemetryError } = await supabase
      .from('telemetry')
      .insert({
        device_id,
        temperature_c: temperature_c ?? null,
        water_percent: water_percent ?? null,
        delta_km: delta_km ?? null,
        gps_lat: gps_lat ?? null,
        gps_lon: gps_lon ?? null,
        ts: ts || new Date().toISOString(),
      })

    if (telemetryError) {
      console.error('Failed to insert telemetry:', telemetryError)
      return new Response(
        JSON.stringify({ error: 'Failed to ingest telemetry' }),
        {
          status: 500,
          headers: { ...corsHeaders, 'Content-Type': 'application/json' },
        }
      )
    }

    // Update device last_seen in device_state
    await supabase
      .from('device_state')
      .upsert({
        device_id,
        last_seen: new Date().toISOString(),
      }, {
        onConflict: 'device_id'
      })

    return new Response(
      JSON.stringify({ success: true, message: 'Telemetry ingested' }),
      {
        status: 200,
        headers: { ...corsHeaders, 'Content-Type': 'application/json' },
      }
    )
  } catch (err) {
    console.error('Error in ingestTelemetry:', err)
    return new Response(
      JSON.stringify({ error: err.message }),
      {
        status: 400,
        headers: { ...corsHeaders, 'Content-Type': 'application/json' },
      }
    )
  }
})

