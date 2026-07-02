<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api'

const deletionRequests = ref([])
const additionRequests = ref([])
const creationRequests = ref([])
const error = ref('')
const emit = defineEmits(['notifications-changed'])

async function load() {
  error.value = ''
  try {
    [deletionRequests.value, additionRequests.value, creationRequests.value] = await Promise.all([
      api('/deletion-requests/'),
      api('/client-group-addition-requests/'),
      api('/client-group-creation-requests/'),
    ])
  } catch (e) { error.value = e.message }
}
async function decide(path, item, decision) {
  const promptText = decision === 'approved' ? 'Коментар до схвалення (необов’язково)' : 'Причина відхилення (необов’язково)'
  const note = window.prompt(promptText, '')
  if (note === null) return
  try {
    await api(`/${path}/${item.id}/decision/`, { method: 'POST', body: JSON.stringify({ decision, note }) })
    await load(); emit('notifications-changed')
  } catch (e) { error.value = e.message }
}
onMounted(load)
</script>

<template>
  <header class="page-header"><div><p class="eyebrow">РІШЕННЯ АДМІНІСТРАТОРА</p><h1>Запити</h1><p>Видалення анкет, додавання клієнтів до груп і створення нових груп.</p></div></header>
  <p v-if="error" class="error">{{ error }}</p>

  <section class="section-block"><h2>Видалення анкет</h2><p>Повна анкета доступна лише поки запит очікує рішення.</p>
    <div class="request-list"><article v-for="item in deletionRequests" :key="item.id" class="panel">
      <div class="request-head"><div><span class="pill">{{ item.status }}</span><h2>{{ item.client.display_name }}</h2></div><small>{{ new Date(item.requested_at).toLocaleString('uk-UA') }}</small></div>
      <p><strong>Автор:</strong> {{ item.requested_by.first_name || item.requested_by.username }} (@{{ item.requested_by.username }})</p><p><strong>Причина:</strong> {{ item.reason }}</p>
      <details v-if="item.status === 'pending'"><summary>Переглянути дані анкети</summary><dl class="columns"><dt>Email</dt><dd>{{ item.client.email }}</dd><dt>Телефон</dt><dd>{{ item.client.phone }}</dd><dt>Послуга</dt><dd>{{ item.client.requested_service }}</dd><dt>Запит</dt><dd>{{ item.client.project_request }}</dd></dl></details>
      <p v-if="item.decision_note"><strong>Коментар рішення:</strong> {{ item.decision_note }}</p>
      <div v-if="item.status === 'pending'" class="actions"><button @click="decide('deletion-requests', item, 'approved')">Схвалити</button><button class="danger" @click="decide('deletion-requests', item, 'rejected')">Відхилити</button></div>
    </article><p v-if="!deletionRequests.length" class="empty panel">Запитів немає.</p></div>
  </section>

  <section class="section-block"><h2>Додавання клієнтів до груп</h2><p>Для рішення показуються лише ім’я або назва клієнта, група та причина.</p>
    <div class="request-list"><article v-for="item in additionRequests" :key="item.id" class="panel">
      <div class="request-head"><div><span class="pill">{{ item.status }}</span><h2>{{ item.client.display_name }} → {{ item.group.name }}</h2></div><small>{{ new Date(item.requested_at).toLocaleString('uk-UA') }}</small></div>
      <p><strong>Автор:</strong> {{ item.requested_by.first_name || item.requested_by.username }} (@{{ item.requested_by.username }})</p><p><strong>Причина:</strong> {{ item.reason }}</p><p v-if="item.decision_note"><strong>Коментар рішення:</strong> {{ item.decision_note }}</p>
      <div v-if="item.status === 'pending'" class="actions"><button @click="decide('client-group-addition-requests', item, 'approved')">Схвалити</button><button class="danger" @click="decide('client-group-addition-requests', item, 'rejected')">Відхилити</button></div>
    </article><p v-if="!additionRequests.length" class="empty panel">Запитів немає.</p></div>
  </section>

  <section class="section-block"><h2>Створення груп</h2>
    <div class="request-list"><article v-for="item in creationRequests" :key="item.id" class="panel">
      <div class="request-head"><div><span class="pill">{{ item.status }}</span><h2>{{ item.proposed_name }}</h2></div><small>{{ new Date(item.requested_at).toLocaleString('uk-UA') }}</small></div>
      <p><strong>Автор:</strong> {{ item.requested_by.first_name || item.requested_by.username }} (@{{ item.requested_by.username }})</p><p><strong>Причина:</strong> {{ item.reason }}</p>
      <p><strong>Клієнти:</strong> {{ item.proposed_clients.map(client => client.display_name).join(', ') || 'не запропоновано' }}</p><p><strong>Відповідальні:</strong> {{ item.proposed_employees.map(employee => `${employee.first_name} ${employee.last_name} (@${employee.username})`).join(', ') || 'не запропоновано' }}; автор запиту додається автоматично.</p>
      <p v-if="item.decision_note"><strong>Коментар рішення:</strong> {{ item.decision_note }}</p>
      <div v-if="item.status === 'pending'" class="actions"><button @click="decide('client-group-creation-requests', item, 'approved')">Схвалити й створити</button><button class="danger" @click="decide('client-group-creation-requests', item, 'rejected')">Відхилити</button></div>
    </article><p v-if="!creationRequests.length" class="empty panel">Запитів немає.</p></div>
  </section>
</template>
