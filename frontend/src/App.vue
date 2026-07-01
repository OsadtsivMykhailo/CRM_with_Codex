<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, auth } from './api'

const router = useRouter()
const user = auth.userState
const unreadCount = ref(0)
const loggedIn = computed(() => Boolean(auth.tokenState.value && user.value))
let notificationTimer = null

async function loadNotifications() {
  if (!loggedIn.value) { unreadCount.value = 0; return }
  try { unreadCount.value = (await api('/notifications/unread-count/')).count }
  catch { unreadCount.value = 0 }
}

async function loadUser() {
  if (!auth.token()) return
  try {
    const currentUser = await api('/auth/me/')
    auth.set(auth.token(), currentUser)
    await loadNotifications()
  } catch {
    auth.clear()
    router.push('/login')
  }
}

async function authenticated(currentUser) {
  auth.updateUser(currentUser)
  await loadNotifications()
}

async function logout() {
  try { await api('/auth/logout/', { method: 'POST' }) }
  finally {
    auth.clear()
    unreadCount.value = 0
    router.push('/login')
  }
}

onMounted(async () => {
  await loadUser()
  notificationTimer = window.setInterval(loadNotifications, 30000)
})
onUnmounted(() => window.clearInterval(notificationTimer))
</script>

<template>
  <div class="shell">
    <aside v-if="loggedIn" class="sidebar">
      <div class="brand"><span>M</span><div>Multisoft<small>CRM alpha</small></div></div>
      <nav>
        <RouterLink to="/">Огляд</RouterLink>
        <RouterLink v-if="user?.role === 'employee'" to="/clients">Клієнти</RouterLink>
        <RouterLink v-if="user?.role === 'client'" to="/my-account">Мій кабінет</RouterLink>
        <template v-if="user?.role === 'admin'">
          <RouterLink to="/employees">Працівники</RouterLink>
          <RouterLink to="/unassigned">Нові клієнти</RouterLink>
          <RouterLink to="/requests">Запити</RouterLink>
          <RouterLink to="/audit">Журнал дій</RouterLink>
        </template>
        <RouterLink class="notification-link" to="/notifications">
          Сповіщення <span v-if="unreadCount" class="badge">{{ unreadCount }}</span>
        </RouterLink>
      </nav>
      <div class="user-card">
        <strong>{{ user?.first_name || user?.username }}</strong>
        <small>{{ user?.role }}</small>
        <button class="ghost" @click="logout">Вийти</button>
      </div>
    </aside>
    <main :class="{ content: loggedIn }">
      <RouterView v-slot="{ Component }">
        <component
          :is="Component"
          :user="user"
          @authenticated="authenticated"
          @notifications-changed="loadNotifications"
        />
      </RouterView>
    </main>
  </div>
</template>
