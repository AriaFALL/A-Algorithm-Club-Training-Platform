// Blog 浮窗编辑器 - 完整功能实现
(function() {
  'use strict';

  let currentTab = 'write';
  let blogContent = '';

  function initBlogEditor() {
    const openButton = document.getElementById('blogOpenButton');
    const overlay = document.getElementById('blogEditorOverlay');
    const closeButton = document.getElementById('blogEditorClose');
    const cancelButton = document.getElementById('blogEditorCancel');
    const saveButton = document.getElementById('blogEditorSave');
    const markdownInput = document.getElementById('blogMarkdownInput');
    const previewPane = document.getElementById('blogPreview');
    const tabs = document.querySelectorAll('.blog-editor-tab');
    const toolbarButtons = document.querySelectorAll('.toolbar-btn');

    if (!openButton || !overlay || !markdownInput) return;

    // 配置 marked.js
    if (typeof marked !== 'undefined') {
      marked.setOptions({
        breaks: true,
        gfm: true,
        headerIds: false,
        mangle: false
      });
    }

    // 打开编辑器
    function openEditor() {
      overlay.setAttribute('aria-hidden', 'false');
      document.body.style.overflow = 'hidden';
      setTimeout(() => markdownInput.focus(), 350);
    }

    // 关闭编辑器
    function closeEditor() {
      overlay.setAttribute('aria-hidden', 'true');
      document.body.style.overflow = '';
    }

    // 保存并关闭
    function saveAndClose() {
      blogContent = markdownInput.value.trim();
      closeEditor();
    }

    // 标签切换
    function switchTab(targetTab) {
      currentTab = targetTab;

      tabs.forEach(t => t.classList.remove('active'));
      document.querySelector(`[data-tab="${targetTab}"]`).classList.add('active');

      document.querySelectorAll('.blog-editor-pane').forEach(pane => {
        pane.classList.remove('active');
      });

      const targetPane = document.querySelector(`[data-pane="${targetTab}"]`);
      if (targetPane) targetPane.classList.add('active');

      // 切换到预览时渲染
      if (targetTab === 'preview') {
        renderPreview();
      }
    }

    // 渲染预览
    function renderPreview() {
      const markdown = markdownInput.value.trim();

      if (!markdown) {
        previewPane.innerHTML = '<p class="preview-placeholder">预览将显示在这里...</p>';
        return;
      }

      try {
        // Reuse the submission reader's HTML filtering without changing editor controls.
        if (typeof renderSubmissionBlog === 'function') {
          renderSubmissionBlog(previewPane, markdown);
        } else {
          previewPane.textContent = markdown;
        }
      } catch (error) {
        console.error('Markdown 渲染错误:', error);
        previewPane.innerHTML = '<p style="color: #cc0000;">预览渲染失败，请检查 Markdown 语法</p>';
      }
    }

    // Markdown 格式化工具栏功能
    function insertMarkdown(action) {
      const textarea = markdownInput;
      const start = textarea.selectionStart;
      const end = textarea.selectionEnd;
      const selectedText = textarea.value.substring(start, end);
      let replacement = '';
      let cursorOffset = 0;

      switch (action) {
        case 'bold':
          replacement = `**${selectedText || '粗体文本'}**`;
          cursorOffset = selectedText ? replacement.length : 2;
          break;
        case 'italic':
          replacement = `*${selectedText || '斜体文本'}*`;
          cursorOffset = selectedText ? replacement.length : 1;
          break;
        case 'heading':
          replacement = `\n## ${selectedText || '标题'}\n`;
          cursorOffset = selectedText ? replacement.length : 3;
          break;
        case 'code':
          if (selectedText.includes('\n')) {
            replacement = `\`\`\`\n${selectedText || '代码块'}\n\`\`\``;
            cursorOffset = selectedText ? replacement.length : 4;
          } else {
            replacement = `\`${selectedText || '代码'}\``;
            cursorOffset = selectedText ? replacement.length : 1;
          }
          break;
        case 'link':
          replacement = `[${selectedText || '链接文本'}](https://)`;
          cursorOffset = selectedText ? replacement.length - 1 : replacement.indexOf('https://') + 8;
          break;
        case 'image':
          replacement = `![${selectedText || '图片描述'}](https://)`;
          cursorOffset = selectedText ? replacement.length - 1 : replacement.indexOf('https://') + 8;
          break;
        case 'list':
          replacement = `\n- ${selectedText || '列表项'}\n`;
          cursorOffset = selectedText ? replacement.length : 2;
          break;
        case 'quote':
          replacement = `\n> ${selectedText || '引用内容'}\n`;
          cursorOffset = selectedText ? replacement.length : 2;
          break;
        case 'math':
          replacement = `$$\n${selectedText || '\\sum_{i=1}^{n} i'}\n$$`;
          cursorOffset = selectedText ? replacement.length : 3;
          break;
        case 'table':
          replacement = `\n| 列1 | 列2 | 列3 |\n|-----|-----|-----|\n| 内容 | 内容 | 内容 |\n`;
          cursorOffset = 2;
          break;
      }

      textarea.value = textarea.value.substring(0, start) + replacement + textarea.value.substring(end);
      textarea.focus();
      textarea.setSelectionRange(start + cursorOffset, start + cursorOffset);
    }

    // 事件监听
    openButton.addEventListener('click', openEditor);
    closeButton.addEventListener('click', closeEditor);
    cancelButton.addEventListener('click', closeEditor);
    saveButton.addEventListener('click', saveAndClose);

    // 点击遮罩层关闭
    overlay.addEventListener('click', function(e) {
      if (e.target === overlay) {
        closeEditor();
      }
    });

    // ESC 键关闭
    document.addEventListener('keydown', function(e) {
      if (e.key === 'Escape' && overlay.getAttribute('aria-hidden') === 'false') {
        closeEditor();
      }
    });

    // 标签切换
    tabs.forEach(tab => {
      tab.addEventListener('click', function() {
        switchTab(this.dataset.tab);
      });
    });

    // 工具栏按钮
    toolbarButtons.forEach(btn => {
      btn.addEventListener('click', function() {
        insertMarkdown(this.dataset.action);
      });
    });

    // 实时预览（可选，如果需要在编辑时实时更新）
    let previewTimeout;
    markdownInput.addEventListener('input', function() {
      clearTimeout(previewTimeout);
      previewTimeout = setTimeout(() => {
        if (currentTab === 'preview') {
          renderPreview();
        }
      }, 500);
    });
  }

  // 获取编辑器内容
  window.getBlogEditorContent = function() {
    const input = document.getElementById('blogMarkdownInput');
    return input ? input.value.trim() : '';
  };

  // 设置编辑器内容
  window.setBlogEditorContent = function(content) {
    const input = document.getElementById('blogMarkdownInput');
    if (input) {
      input.value = content || '';
    }
  };

  // 清空编辑器
  window.clearBlogEditor = function() {
    const input = document.getElementById('blogMarkdownInput');
    const preview = document.getElementById('blogPreview');

    if (input) input.value = '';
    if (preview) preview.innerHTML = '<p class="preview-placeholder">预览将显示在这里...</p>';

    currentTab = 'write';

    // 切换回编辑标签
    const tabs = document.querySelectorAll('.blog-editor-tab');
    const panes = document.querySelectorAll('.blog-editor-pane');
    tabs.forEach((tab, i) => {
      if (i === 0) tab.classList.add('active');
      else tab.classList.remove('active');
    });
    panes.forEach((pane, i) => {
      if (i === 0) pane.classList.add('active');
      else pane.classList.remove('active');
    });
  };

  // DOM 加载完成后初始化
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initBlogEditor);
  } else {
    initBlogEditor();
  }
})();
