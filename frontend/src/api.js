import { ref } from 'vue'

const TOKEN_KEY = 'crm_token'
const USER_KEY = 'crm_user'

function storedUser() {
  try { return JSON.parse(localStorage.getItem(USER_KEY) || 'null') }
  catch { return null }
}

const tokenState = ref(localStorage.getItem(TOKEN_KEY))
const userState = ref(storedUser())

export const auth = {
  tokenState,
  userState,
  token: () => tokenState.value,
  user: () => userState.value,
  set(token, user) {
    tokenState.value = token
    userState.value = user
    localStorage.setItem(TOKEN_KEY, token)
    localStorage.setItem(USER_KEY, JSON.stringify(user))
  },
  updateUser(user) {
    userState.value = user
    localStorage.setItem(USER_KEY, JSON.stringify(user))
  },
  clear() {
    tokenState.value = null
    userState.value = null
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
  },
}

function errorMessage(data) {
  if (typeof data?.detail === 'string') return data.detail
  const values = Object.values(data || {}).flat(Infinity).filter(Boolean)
  return values.join(' ') || 'Помилка запиту'
}

export async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) }
  if (!(options.body instanceof FormData)) headers['Content-Type'] = 'application/json'
  if (auth.token()) headers.Authorization = `Token ${auth.token()}`
  const response = await fetch(`/api${path}`, { ...options, headers })
  if (response.status === 204) return null
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(errorMessage(data))
  return data
}
