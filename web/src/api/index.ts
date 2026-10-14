import * as live from './live'
import * as mock from './mock'

export const api = import.meta.env.VITE_API_MODE === 'live' ? live : mock

export { useApi } from './useApi'
export type * from './types'
