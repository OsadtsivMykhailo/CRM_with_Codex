<script setup>
import { nextTick, ref, watch } from 'vue'

const props = defineProps({
  modelValue: { type: String, default: '' },
  variables: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:modelValue'])
const editor = ref(null)

watch(() => props.modelValue, async (value) => {
  await nextTick()
  if (editor.value && editor.value.innerHTML !== value) editor.value.innerHTML = value || ''
}, { immediate: true })

function update() {
  emit('update:modelValue', editor.value?.innerHTML || '')
}

function command(name, value = null) {
  editor.value?.focus()
  document.execCommand(name, false, value)
  update()
}

function addLink() {
  const url = window.prompt('Адреса посилання (https://...)')
  if (url) command('createLink', url)
}
</script>

<template>
  <div class="rich-editor">
    <div class="editor-toolbar">
      <button type="button" title="Жирний" @click="command('bold')"><strong>B</strong></button>
      <button type="button" title="Курсив" @click="command('italic')"><em>I</em></button>
      <button type="button" title="Підкреслення" @click="command('underline')"><u>U</u></button>
      <button type="button" @click="command('formatBlock', 'h2')">Заголовок</button>
      <button type="button" @click="command('insertUnorderedList')">• Список</button>
      <button type="button" @click="command('insertOrderedList')">1. Список</button>
      <button type="button" @click="addLink">Посилання</button>
      <button type="button" @click="command('removeFormat')">Очистити формат</button>
      <button v-for="item in props.variables" :key="item.value" type="button" :title="item.description" @click="command('insertText', item.value)">{{ item.label }}</button>
    </div>
    <div ref="editor" class="editor-area" contenteditable="true" @input="update" />
  </div>
</template>
