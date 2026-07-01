<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
const router = useRouter()
const notifications = ref([])
const error = ref('')
const emit = defineEmits(['notifications-changed'])
async function load() { try { notifications.value = await api('/notifications/') } catch (e) { error.value = e.message } }
function target(item) {
  if (item.kind === 'client_self_registered') return '/unassigned'
  if (item.kind === 'deletion_request_created') return '/requests'
  if (item.kind === 'client_assigned') return `/clients/${item.entity_id}`
  return null
}
async function open(item) {
  if (!item.read_at) await api(`/notifications/${item.id}/mark-read/`, { method: 'POST' })
  emit('notifications-changed')
  const path = target(item)
  if (path) router.push(path); else load()
}
onMounted(load)
</script>

<template>
  <header class="page-header"><div><p class="eyebrow">ПОВІДОМЛЕННЯ</p><h1>Сповіщення</h1></div></header><p v-if="error" class="error">{{ error }}</p>
  <section class="notification-list"><button v-for="item in notifications" :key="item.id" class="notification-card" :class="{ unread: !item.read_at }" @click="open(item)"><span><strong>{{ item.title }}</strong><small>{{ item.message }}</small></span><time>{{ new Date(item.created_at).toLocaleString('uk-UA') }}</time></button><p v-if="!notifications.length" class="empty panel">Сповіщень поки немає.</p></section>
</template>
