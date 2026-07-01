<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api'

const clients = ref([])
const employees = ref([])
const selections = ref({})
const error = ref('')
const message = ref('')

function clearFeedback() { error.value = ''; message.value = '' }
async function load() {
  try { [clients.value, employees.value] = await Promise.all([api('/clients/unassigned/'), api('/auth/employees/')]) }
  catch (e) { error.value = e.message }
}
async function assign(client) {
  clearFeedback()
  const employeeId = selections.value[client.id]
  if (!employeeId) { error.value = 'Оберіть працівника.'; return }
  try {
    await api(`/clients/${client.id}/assign/`, { method: 'POST', body: JSON.stringify({ employee_id: Number(employeeId) }) })
    message.value = `Клієнта «${client.display_name}» призначено.`
    await load()
  } catch (e) { error.value = e.message }
}
async function rejectRegistration(client) {
  clearFeedback()
  const reason = window.prompt(`Причина відхилення реєстрації «${client.display_name}»:`)
  if (reason === null) return
  if (reason.trim().length < 10) { error.value = 'Причина має містити щонайменше 10 символів.'; return }
  try {
    await api(`/clients/${client.id}/reject-registration/`, { method: 'POST', body: JSON.stringify({ reason: reason.trim() }) })
    message.value = `Реєстрацію «${client.display_name}» відхилено.`
    await load()
  } catch (e) { error.value = e.message }
}
onMounted(load)
</script>

<template>
  <header class="page-header"><div><p class="eyebrow">НОВІ КЛІЄНТИ</p><h1>Пул без відповідального</h1><p>Адміністратор бачить лише ім’я або назву компанії та призначає працівника.</p></div></header>
  <p v-if="message" class="success">{{ message }}</p><p v-if="error" class="error">{{ error }}</p>
  <div class="table-wrap"><table><thead><tr><th>Клієнт</th><th>Причина появи</th><th>Дата</th><th>Дії</th></tr></thead><tbody>
    <tr v-for="client in clients" :key="client.id">
      <td><strong>{{ client.display_name }}</strong></td>
      <td><span class="pill" :class="{ repeated: client.pool_reason !== 'self_registered' }">{{ client.pool_reason_label }}</span></td>
      <td>{{ new Date(client.created_at).toLocaleString('uk-UA') }}</td>
      <td class="assign-cell"><select v-model="selections[client.id]"><option value="">Оберіть працівника</option><option v-for="employee in employees.filter(item => item.is_active)" :key="employee.user_id" :value="employee.user_id">{{ employee.first_name }} {{ employee.last_name }} (@{{ employee.username }})</option></select><button @click="assign(client)">Призначити</button><button v-if="client.pool_reason === 'self_registered'" class="danger" @click="rejectRegistration(client)">Відхилити</button></td>
    </tr>
    <tr v-if="!clients.length"><td colspan="4" class="empty">Усі анкети вже розподілено.</td></tr>
  </tbody></table></div>
</template>
