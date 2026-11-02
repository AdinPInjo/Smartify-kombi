/**
 * Ingest Telemetry Edge Function
 * Accepts telemetry data from devices and stores in Supabase
 */

import { serve } from 'https://deno.land/std@0.168.0/http/server.ts'
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2'
import { corsHeaders } from '../_shared/cors.ts'
import { validateDeviceToken } from '../_shared/auth.ts'

/**
 * Extract device token from request headers
 * Priority:
 * 1. x-device-token header (preferred)
 * 2. Authorization: Bearer <token> (fallback)
 */
function extractDeviceToken(req: Request): string | null {
  // Try x-device-token header first (preferred)
  const xDeviceToken = req.headers.get('x-device-token')
  if (xDeviceToken && xDeviceToken.trim()) {
    return xDeviceToken.trim()
  }

  // Fallback to Authorization Bearer token
  const authHeader = req.headers.get('Authorization')
  if (authHeader && authHeader.startsWith('Bearer ')) {
    const token = authHeader.substring(7).trim()
    if (token) {
      return token
    }
  }

  return null
}

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

    // Extract and validate device token
    const deviceToken = extractDeviceToken(req)
    
    if (!deviceToken) {
      return new Response(
        JSON.stringify({ error: 'Missing device token' }),
        {
          status: 401,
          headers: { ...corsHeaders, 'Content-Type': 'application/json' },
        }
      )
    }

    const { device_id, error: authError } = await validateDeviceToken(supabase, deviceToken)

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
      temp_kombi_c,
      temp_garaza_c,
      temp_outside_c,
      humidity_kombi,
      humidity_garaza,
      water_percent,
      delta_km,
      gps_lat,
      gps_lon,
      relays,
      ts,
    } = payload

    // Insert telemetry
    const { error: telemetryError } = await supabase
      .from('telemetry')
      .insert({
        device_id,
        temperature_c: temperature_c ?? temp_kombi_c ?? null,
        temp_kombi_c: temp_kombi_c ?? null,
        temp_garaza_c: temp_garaza_c ?? null,
        temp_outside_c: temp_outside_c ?? null,
        humidity_kombi: humidity_kombi ?? null,
        humidity_garaza: humidity_garaza ?? null,
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

    // Update device last_seen and current_state in device_state
    // Build current_state snapshot with relay states for bi-directional sync
    const currentState: any = {}
    
    // Add relay states if provided (for bi-directional sync)
    if (relays && typeof relays === 'object') {
      currentState.relays = relays
    }
    
    // Add other telemetry data to current_state
    if (temperature_c !== undefined && temperature_c !== null) {
      currentState.temperature_c = temperature_c
    }
    if (temp_kombi_c !== undefined && temp_kombi_c !== null) {
      currentState.temp_kombi_c = temp_kombi_c
    }
    if (temp_garaza_c !== undefined && temp_garaza_c !== null) {
      currentState.temp_garaza_c = temp_garaza_c
    }
    if (temp_outside_c !== undefined && temp_outside_c !== null) {
      currentState.temp_outside_c = temp_outside_c
    }
    if (humidity_kombi !== undefined && humidity_kombi !== null) {
      currentState.humidity_kombi = humidity_kombi
    }
    if (humidity_garaza !== undefined && humidity_garaza !== null) {
      currentState.humidity_garaza = humidity_garaza
    }
    if (water_percent !== undefined && water_percent !== null) {
      currentState.water_percent = water_percent
    }
    if (gps_lat !== undefined && gps_lat !== null && gps_lon !== undefined && gps_lon !== null) {
      currentState.gps = {
        lat: gps_lat,
        lon: gps_lon,
        fix: true,
      }
    }
    
    await supabase
      .from('device_state')
      .upsert({
        device_id,
        last_seen: new Date().toISOString(),
        current_state: currentState,
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
