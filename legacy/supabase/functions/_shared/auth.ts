/**
 * Device authentication utilities
 * Validates device tokens by hashing and matching against devices.token_hash
 */

import { createClient, SupabaseClient } from 'https://esm.sh/@supabase/supabase-js@2'

/**
 * Hash a token using SHA-256
 */
export async function hashToken(token: string): Promise<string> {
  const encoder = new TextEncoder()
  const data = encoder.encode(token)
  const hashBuffer = await crypto.subtle.digest('SHA-256', data)
  const hashArray = Array.from(new Uint8Array(hashBuffer))
  const hashHex = hashArray.map(b => b.toString(16).padStart(2, '0')).join('')
  return hashHex
}

/**
 * Validate device token and return device_id
 */
export async function validateDeviceToken(
  supabase: SupabaseClient,
  authHeader: string | null
): Promise<{ device_id: string | null; error: string | null }> {
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    return { device_id: null, error: 'Missing or invalid Authorization header' }
  }

  const token = authHeader.substring(7) // Remove 'Bearer ' prefix

  if (!token) {
    return { device_id: null, error: 'Empty device token' }
  }

  try {
    const tokenHash = await hashToken(token)

    const { data, error } = await supabase
      .from('devices')
      .select('id')
      .eq('token_hash', tokenHash)
      .single()

    if (error || !data) {
      console.error('Device token validation failed:', error?.message || 'No device found')
      return { device_id: null, error: 'Invalid device token' }
    }

    return { device_id: data.id, error: null }
  } catch (err) {
    console.error('Error validating device token:', err)
    return { device_id: null, error: 'Token validation error' }
  }
}

