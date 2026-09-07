import { useEffect, useRef, useState } from 'react'
import { hasValidConfig, isDemoMode } from '../lib/api'

// The backend is read-only REST (no websockets), so "realtime" is polling:
// we call onUpdate every 30s and report a connected/last-updated status the
// header uses for its live indicator.
export const useRealtime = (onUpdate: () => void) => {
    const [isConnected, setIsConnected] = useState(false)
    const [lastUpdated, setLastUpdated] = useState(new Date())
    const cb = useRef(onUpdate)
    cb.current = onUpdate

    useEffect(() => {
        if (isDemoMode) {
            setIsConnected(true)
            return
        }
        if (!hasValidConfig()) {
            setIsConnected(false)
            return
        }
        setIsConnected(true)
        const id = setInterval(() => {
            setLastUpdated(new Date())
            cb.current()
        }, 30000)
        return () => clearInterval(id)
    }, [])

    return { isConnected, lastUpdated }
}
