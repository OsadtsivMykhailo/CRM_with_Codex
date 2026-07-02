<script setup>
import { onMounted, reactive, ref } from 'vue'
import { api } from '../api'
import RichTextEditor from '../components/RichTextEditor.vue'

const templates = ref([])
const error = ref('')
const message = ref('')
const templateId = ref(null)
const form = reactive({ name: '', scope: 'company', message_type: 'service', subject: '', html_body: '<p></p>', text_body: '' })
const variables = [
  { value: '{{FirstName}}', label: 'Ім’я', description: 'Ім’я клієнта або контактної особи' },
  { value: '{{CompanyName}}', label: 'Компанія клієнта', description: 'Назва компанії клієнта' },
  { value: '{{Company}}', label: 'Наша компанія', description: 'Назва компанії-відправника' },
]

async function load() { try { templates.value = await api('/email-templates/') } catch (e) { error.value = e.message } }
function reset() { templateId.value = null; Object.assign(form, { name: '', scope: 'company', message_type: 'service', subject: '', html_body: '<p></p>', text_body: '' }) }
function edit(item) { templateId.value = item.id; Object.assign(form, { ...item, scope: 'company' }) }
function insertSubjectVariable(event) { if (event.target.value) form.subject += event.target.value; event.target.value = '' }
async function save() {
  error.value = ''; message.value = ''
  try {
    const path = templateId.value ? `/email-templates/${templateId.value}/` : '/email-templates/'
    await api(path, { method: templateId.value ? 'PATCH' : 'POST', body: JSON.stringify(form) })
    reset(); await load(); message.value = 'Спільний шаблон збережено.'
  } catch (e) { error.value = e.message }
}
async function remove(item) {
  if (!window.confirm(`Видалити шаблон «${item.name}»?`)) return
  try { await api(`/email-templates/${item.id}/`, { method: 'DELETE' }); await load() }
  catch (e) { error.value = e.message }
}
onMounted(load)
</script>

<template>
  <header class="page-header"><div><RouterLink to="/email-settings">← До Email-налаштувань</RouterLink><p class="eyebrow">КОРПОРАТИВНА ПОШТА</p><h1>Спільні шаблони</h1><p>Доступні всім працівникам, редагуються лише адміністратором.</p></div></header>
  <p v-if="message" class="success">{{ message }}</p><p v-if="error" class="error">{{ error }}</p>
  <section class="panel section-block">
    <form class="grid two" @submit.prevent="save">
      <label>Назва шаблону<input v-model="form.name" required /></label><label>Тип<select v-model="form.message_type"><option value="service">Службовий</option><option value="marketing">Рекламний</option></select></label>
      <label class="span-two">Тема<input v-model="form.subject" required /><select aria-label="Додати змінну до теми" @change="insertSubjectVariable"><option value="">+ Додати змінну</option><option v-for="item in variables" :key="item.value" :value="item.value">{{ item.label }} — {{ item.value }}</option></select></label>
      <label class="span-two">Вміст<RichTextEditor v-model="form.html_body" :variables="variables" /></label>
      <label class="span-two">Текстова версія<textarea v-model="form.text_body" rows="4" placeholder="Необов’язково" /></label>
      <div class="span-two"><small v-for="item in variables" :key="item.value"><code>{{ item.value }}</code> — {{ item.description }}<br /></small></div>
      <div class="span-two actions"><button>{{ templateId ? 'Оновити шаблон' : 'Створити шаблон' }}</button><button v-if="templateId" type="button" class="secondary" @click="reset">Скасувати</button></div>
    </form>
    <div class="simple-list"><div v-for="item in templates" :key="item.id" class="list-row"><span><strong>{{ item.name }}</strong><small>{{ item.subject }} · {{ item.message_type === 'marketing' ? 'рекламний' : 'службовий' }}</small></span><span class="actions"><button class="small secondary" @click="edit(item)">Редагувати</button><button class="small danger" @click="remove(item)">Видалити</button></span></div></div>
  </section>
</template>
