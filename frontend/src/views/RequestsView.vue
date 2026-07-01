<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api'

const requests = ref([])
const error = ref('')
const emit = defineEmits(['notifications-changed'])
async function load() { try { requests.value = await api('/deletion-requests/') } catch (e) { error.value = e.message } }
async function decide(item, decision) {
  const promptText = decision === 'approved' ? 'Коментар до схвалення (необов’язково)' : 'Причина відхилення (необов’язково)'
  const note = window.prompt(promptText, '')
  if (note === null) return
  try { await api(`/deletion-requests/${item.id}/decision/`, { method: 'POST', body: JSON.stringify({ decision, note }) }); await load(); emit('notifications-changed') }
  catch (e) { error.value = e.message }
}
onMounted(load)
</script>

<template>
  <header class="page-header"><div><p class="eyebrow">РІШЕННЯ АДМІНІСТРАТОРА</p><h1>Запити на видалення</h1><p>Повна анкета доступна адміністратору лише поки запит очікує рішення.</p></div></header>
  <p v-if="error" class="error">{{ error }}</p>
  <section class="request-list">
    <article v-for="item in requests" :key="item.id" class="panel">
      <div class="request-head"><div><span class="pill">{{ item.status }}</span><h2>{{ item.client.display_name }}</h2></div><small>{{ new Date(item.requested_at).toLocaleString('uk-UA') }}</small></div>
      <p><strong>Автор:</strong> {{ item.requested_by.first_name || item.requested_by.username }} (@{{ item.requested_by.username }})</p><p><strong>Причина:</strong> {{ item.reason }}</p>
      <details v-if="item.status === 'pending'"><summary>Переглянути дані анкети</summary><dl class="columns"><dt>Email</dt><dd>{{ item.client.email }}</dd><dt>Телефон</dt><dd>{{ item.client.phone }}</dd><dt>Послуга</dt><dd>{{ item.client.requested_service }}</dd><dt>Запит</dt><dd>{{ item.client.project_request }}</dd></dl></details>
      <p v-if="item.decision_note"><strong>Коментар рішення:</strong> {{ item.decision_note }}</p>
      <div v-if="item.status === 'pending'" class="actions"><button @click="decide(item, 'approved')">Схвалити</button><button class="danger" @click="decide(item, 'rejected')">Відхилити</button></div>
    </article>
    <p v-if="!requests.length" class="empty panel">Запитів поки немає.</p>
  </section>
</template>
