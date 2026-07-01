<script setup>
import { onMounted, reactive, ref } from 'vue'
import { api } from '../api'

const events = ref([]), employees = ref([]), actions = ref([]), error = ref('')
const count = ref(0), page = ref(1), hasNext = ref(false), hasPrevious = ref(false)
const filters = reactive({ search: '', actor: '', action: '', date_from: '', date_to: '' })

async function load(targetPage = 1) {
  error.value = ''
  const params = new URLSearchParams({ page: String(targetPage) })
  Object.entries(filters).forEach(([key, value]) => { if (value) params.set(key, value) })
  try {
    const data = await api(`/audit/?${params}`)
    events.value = data.results; count.value = data.count; page.value = targetPage
    hasNext.value = Boolean(data.next); hasPrevious.value = Boolean(data.previous)
  } catch (e) { error.value = e.message }
}
function reset() { Object.assign(filters, { search: '', actor: '', action: '', date_from: '', date_to: '' }); load(1) }
function actor(event) { return event.actor ? (event.actor.first_name || event.actor.username) : 'Система' }
function changes(event) {
  if (event.changes?.reason) return event.changes.reason
  return event.changes?.fields?.join(', ') || Object.keys(event.changes || {}).join(', ') || '—'
}
onMounted(async () => {
  try { [employees.value, actions.value] = await Promise.all([api('/auth/employees/'), api('/audit/actions/')]) }
  catch (e) { error.value = e.message }
  await load()
})
</script>

<template>
  <header class="page-header"><div><p class="eyebrow">НЕЗМІННА ІСТОРІЯ</p><h1>Журнал дій</h1><p>У базі зберігається повна історія; на сторінці відображається по 30 записів.</p></div></header>
  <form class="panel audit-filters" @submit.prevent="load(1)">
    <label>Пошук за клієнтом або дією<input v-model="filters.search" placeholder="Ім’я, компанія або операція" /></label>
    <label>Працівник<select v-model="filters.actor"><option value="">Усі</option><option v-for="employee in employees" :key="employee.user_id" :value="employee.user_id">{{ employee.first_name }} {{ employee.last_name }} (@{{ employee.username }})</option></select></label>
    <label>Тип операції<select v-model="filters.action"><option value="">Усі</option><option v-for="item in actions" :key="item" :value="item">{{ item }}</option></select></label>
    <label>Від дати<input v-model="filters.date_from" type="date" /></label><label>До дати<input v-model="filters.date_to" type="date" /></label>
    <div class="actions"><button>Застосувати</button><button type="button" class="secondary" @click="reset">Очистити</button></div>
  </form>
  <p v-if="error" class="error">{{ error }}</p>
  <div class="table-wrap"><table><thead><tr><th>Час</th><th>Хто</th><th>Дія</th><th>Об’єкт</th><th>Поля / причина</th></tr></thead><tbody>
    <tr v-for="event in events" :key="event.id"><td>{{ new Date(event.created_at).toLocaleString('uk-UA') }}</td><td>{{ actor(event) }}</td><td><code>{{ event.action }}</code></td><td>{{ event.entity_label || `${event.entity_type} #${event.entity_id}` }}</td><td>{{ changes(event) }}</td></tr>
    <tr v-if="!events.length"><td colspan="5" class="empty">За вибраними умовами подій немає.</td></tr>
  </tbody></table></div>
  <footer class="pagination"><span>Усього: {{ count }} · Сторінка {{ page }}</span><div class="actions"><button class="secondary" :disabled="!hasPrevious" @click="load(page - 1)">← Попередня</button><button class="secondary" :disabled="!hasNext" @click="load(page + 1)">Наступна →</button></div></footer>
</template>
