<template>
  <div class="page-grid">
    <NCard :title="`小说详情 · ${novelId}`">
      <NSpace>
        <NButton @click="goBack">← 返回列表</NButton>
        <NButton type="primary" @click="onReloadAll">{{ t('common.refresh') }}</NButton>
      </NSpace>
    </NCard>

    <NTabs v-model:value="activeTab" type="card" animated>

      <!-- ═══ Tab 1: 章节管理 ═══ -->
      <NTabPane name="chapters" :tab="t('novels.chapterList')">
        <NCard>
          <NButton @click="showAddChapter = !showAddChapter" style="margin-bottom:12px">
            {{ showAddChapter ? "收起" : "+ 新增章节" }}
          </NButton>

          <template v-if="showAddChapter">
            <NGrid :cols="2" :x-gap="8" :y-gap="8" responsive="screen" item-responsive style="margin-bottom:12px">
              <NGridItem span="0:2 900:1">
                <NFormItem label="章节号"><NInputNumber v-model:value="newChapterNo" :min="1" /></NFormItem>
              </NGridItem>
              <NGridItem span="0:2 900:1">
                <NFormItem label="语言">
                  <NSelect v-model:value="newChapterLanguage" :options="languageOptions" />
                </NFormItem>
              </NGridItem>
              <NGridItem span="0:2">
                <NFormItem label="章节标题"><NInput v-model:value="newChapterTitle" /></NFormItem>
              </NGridItem>
            </NGrid>
            <NFormItem label="章节内容">
              <NInput v-model:value="newChapterContent" type="textarea" :autosize="{ minRows: 4, maxRows: 10 }" />
            </NFormItem>
            <NSpace style="margin-bottom:12px">
              <NButton type="primary" @click="onCreateChapter">创建章节</NButton>
              <NButton @click="showAddChapter = false">{{ t('common.cancel') }}</NButton>
            </NSpace>
          </template>

          <NDataTable :columns="chapterColumns" :data="chapters" :pagination="{ pageSize: 10 }" />
        </NCard>
      </NTabPane>

      <!-- ═══ Tab 2: 影视团队 ═══ -->
      <NTabPane name="team" :tab="t('novels.filmCrew')">
        <NCard>
          <NText depth="3" style="display:block;margin-bottom:16px">
            第一步：勾选本项目需要的职位。第二步：为每个职位指定 Persona 实例。
          </NText>

          <NDivider>第一步：选择职位</NDivider>
          <NSpace style="margin-bottom:8px" align="center">
            <NButton size="small" @click="onSelectAllRoles">全选</NButton>
            <NButton size="small" @click="onClearAllRoles">清空</NButton>
            <NText depth="3" style="font-size:12px">共 {{ ALL_ROLE_TEMPLATES.length }} 个可用职位，已选 {{ selectedRoleKeys.length }} 个</NText>
          </NSpace>
          <NCheckboxGroup v-model:value="selectedRoleKeys" style="margin-bottom:16px">
            <NGrid :cols="4" :x-gap="8" :y-gap="6" responsive="screen" item-responsive>
              <NGridItem v-for="role in ALL_ROLE_TEMPLATES" :key="role.id" span="0:4 640:2 1100:1">
                <NCheckbox :value="role.id" :label="`${role.label} (${role.id})`" />
              </NGridItem>
            </NGrid>
          </NCheckboxGroup>

          <template v-if="selectedRoleKeys.length > 0">
            <NDivider>第二步：绑定 Persona</NDivider>
            <NGrid :cols="2" :x-gap="12" :y-gap="10" responsive="screen" item-responsive>
              <NGridItem v-for="roleKey in selectedRoleKeys" :key="roleKey" span="0:2 900:1">
                <NFormItem :label="roleLabelMap[roleKey] ?? roleKey">
                  <NSelect
                    v-model:value="teamBindings[roleKey]"
                    :options="personaOptions"
                    :placeholder="`选择 ${roleLabelMap[roleKey] ?? roleKey} 的 Persona`"
                    clearable
                    filterable
                    style="flex:1"
                  />
                </NFormItem>
              </NGridItem>
            </NGrid>
          </template>
          <NEmpty v-else description="请在上方勾选需要的职位" style="margin:24px 0" />

          <NSpace style="margin-top:12px">
            <NButton type="primary" :loading="isSavingTeam" :disabled="selectedRoleKeys.length === 0" @click="onSaveTeam">保存团队绑定</NButton>
            <NButton @click="onLoadTeam">重新加载</NButton>
          </NSpace>
          <pre v-if="teamSaveResult" class="json-panel" style="margin-top:12px">{{ teamSaveResult }}</pre>
        </NCard>
      </NTabPane>

      <!-- ═══ Tab 3: 剧本转换 (新增) ═══ -->
      <NTabPane name="script" :tab="t('script.title')">
        <NCard>
          <NGrid :cols="3" :x-gap="8" :y-gap="8" responsive="screen" item-responsive style="margin-bottom:12px">
            <NGridItem span="0:3 900:1">
              <NFormItem label="章节">
                <NSelect
                  v-model:value="scriptChapterId"
                  :options="chapterOptions"
                  placeholder="选择章节"
                  filterable
                />
              </NFormItem>
            </NGridItem>
            <NGridItem span="0:3 900:1">
              <NFormItem :label="t('script.granularity')">
                <NSelect v-model:value="scriptGranularity" :options="granularityOptions" />
              </NFormItem>
            </NGridItem>
            <NGridItem span="0:3 900:1">
              <NFormItem label="模型 Provider">
                <NSelect v-model:value="scriptProviderId" :options="providerOptions" filterable placeholder="选择 Provider" />
              </NFormItem>
            </NGridItem>
          </NGrid>

          <!-- Format detect result -->
          <template v-if="formatDetectResult">
            <NAlert type="info" style="margin-bottom:12px">
              格式检测：<strong>{{ formatDetectResult.format }}</strong>
              （置信度 {{ (formatDetectResult.confidence * 100).toFixed(0) }}%，方法：{{ formatDetectResult.method }}）
              <span v-if="formatDetectResult.signals.length">
                — 信号：{{ formatDetectResult.signals.join('、') }}
              </span>
            </NAlert>
          </template>

          <NSpace style="margin-bottom:16px">
            <NButton
              :loading="isDetectingFormat"
              :disabled="!scriptChapterId"
              @click="onDetectFormat"
            >{{ t('script.formatDetect') }}</NButton>
            <NButton
              :loading="isLoadingScript"
              :disabled="!scriptChapterId"
              @click="onLoadScript"
            >{{ t('script.loadExisting') }}</NButton>
            <NButton
              type="primary"
              :loading="isConvertingScript"
              :disabled="!scriptChapterId || !scriptProviderId"
              @click="onGenerateScript"
            >{{ t('script.novelToScript') }}</NButton>
            <NButton
              type="warning"
              :loading="isNormalizingScript"
              :disabled="!scriptChapterId || !scriptProviderId"
              @click="onRegenerateScript"
            >{{ t('script.regenerate') }}</NButton>
          </NSpace>

          <!-- Version info bar -->
          <template v-if="scriptResult">
            <NAlert type="success" style="margin-bottom:12px" v-if="scriptResult.cached">
              已加载缓存版本 v{{ scriptResult.version }}
              <template v-if="scriptResult.script_updated_at">
                ·更新于 {{ new Date(scriptResult.script_updated_at).toLocaleString() }}
              </template>
              <template v-if="scriptResult.run_id"> · Run: {{ scriptResult.run_id.substring(0, 8) }}</template>
            </NAlert>
            <NAlert type="info" style="margin-bottom:12px" v-else>
              新生成版本 v{{ scriptResult.version }}
              <template v-if="scriptResult.script_updated_at">
                · {{ new Date(scriptResult.script_updated_at).toLocaleString() }}
              </template>
            </NAlert>
          </template>

          <!-- Scenes preview -->
          <template v-if="scriptResult && scriptResult.scenes.length">
            <NDivider>{{ t('script.scenes') }}（{{ scriptResult.scenes.length }} 个）</NDivider>
            <NText v-if="scriptResult.summary" depth="3" style="display:block;margin-bottom:8px">
              摘要：{{ scriptResult.summary }}
            </NText>
            <NCollapse>
              <NCollapseItem
                v-for="scene in scriptResult.scenes"
                :key="scene.scene_id"
                :title="`${scene.scene_id} · ${scene.location || '?'} · ${scene.time || ''}`"
                :name="scene.scene_id"
              >
                <NDescriptions :column="2" bordered size="small" style="margin-bottom:8px">
                  <NDescriptionsItem label="地点">{{ scene.location }}</NDescriptionsItem>
                  <NDescriptionsItem label="时间">{{ scene.time }}</NDescriptionsItem>
                  <NDescriptionsItem label="天气">{{ scene.weather }}</NDescriptionsItem>
                  <NDescriptionsItem label="氛围">{{ scene.mood }}</NDescriptionsItem>
                </NDescriptions>
                <NText v-if="scene.narration" style="display:block;margin-bottom:8px;white-space:pre-wrap">
                  {{ scene.narration }}
                </NText>
                <template v-if="scene.dialogue_blocks?.length">
                  <div
                    v-for="(d, di) in scene.dialogue_blocks"
                    :key="di"
                    style="margin-bottom:4px"
                  >
                    <NTag size="small" style="margin-right:6px">{{ d.speaker || '旁白' }}</NTag>
                    <NText>{{ d.line }}</NText>
                  </div>
                </template>
              </NCollapseItem>
            </NCollapse>
          </template>
          <NEmpty v-else-if="scriptResult" description="场景为空，请重新转换" />
        </NCard>
      </NTabPane>

      <!-- ═══ Tab 4: 世界模型抽离 (替换原实体抽离) ═══ -->
      <NTabPane name="entities" :tab="t('world.title')">
        <NCard>
          <NGrid :cols="3" :x-gap="8" :y-gap="8" responsive="screen" item-responsive style="margin-bottom:12px">
            <NGridItem span="0:3 900:1">
              <NFormItem label="章节">
                <NSelect
                  v-model:value="worldChapterId"
                  :options="chapterOptions"
                  placeholder="选择章节"
                  filterable
                />
              </NFormItem>
            </NGridItem>
            <NGridItem span="0:3 900:1">
              <NFormItem :label="t('world.extractionLevel')">
                <NSelect v-model:value="worldLevel" :options="extractionLevelOptions" />
              </NFormItem>
            </NGridItem>
            <NGridItem span="0:3 900:1">
              <NFormItem label="模型 Provider">
                <NSelect v-model:value="worldProviderId" :options="providerOptions" filterable placeholder="选择 Provider" />
              </NFormItem>
            </NGridItem>
          </NGrid>

          <NSpace style="margin-bottom:16px">
            <NButton
              :loading="isLoadingWorld"
              :disabled="!worldChapterId"
              @click="onLoadWorldModel"
            >{{ t('world.loadExisting') }}</NButton>
            <NButton
              type="primary"
              :loading="isExtractingWorld"
              :disabled="!worldCanGenerate"
              @click="onGenerateWorldModel"
            >
              {{ isExtractingWorld ? "抽离中（约60-90s）..." : t('world.extract') }}
            </NButton>
            <NButton
              type="warning"
              :loading="isRegeneratingWorld"
              :disabled="!worldCanRegenerate"
              @click="onRegenerateWorldModel"
            >{{ t('world.regenerate') }}</NButton>
            <NButton
              :loading="isBuildingMapping"
              :disabled="!novelId"
              @click="onBuildEntityMapping"
            >{{ t('world.writeToMapping') }}</NButton>
          </NSpace>

          <!-- World model version info -->
          <template v-if="worldResult">
            <NAlert
              :type="worldResult.cached ? 'success' : 'info'"
              style="margin-bottom:12px"
            >
              {{ worldResult.cached ? '已加载缓存版本' : '新生成版本' }} v{{ worldResult.version }}
              <template v-if="worldResult.world_model_updated_at">
                · {{ new Date(worldResult.world_model_updated_at).toLocaleString() }}
              </template>
            </NAlert>
          </template>

          <template v-if="worldResult">
            <NTabs type="line" animated>
              <!-- 人物 -->
              <NTabPane name="characters" :tab="`${t('world.characters')}（${worldResult.characters.length}）`">
                <NDataTable
                  :columns="characterColumns"
                  :data="worldResult.characters"
                  :pagination="{ pageSize: 10 }"
                  size="small"
                />
              </NTabPane>
              <!-- 场景 -->
              <NTabPane name="locations" :tab="`${t('world.locations')}（${worldResult.locations.length}）`">
                <NDataTable
                  :columns="locationColumns"
                  :data="worldResult.locations"
                  :pagination="{ pageSize: 10 }"
                  size="small"
                />
              </NTabPane>
              <!-- 道具 -->
              <NTabPane name="props" :tab="`${t('world.props')}（${worldResult.props.length}）`">
                <NDataTable
                  :columns="propColumns"
                  :data="worldResult.props"
                  :pagination="{ pageSize: 10 }"
                  size="small"
                />
              </NTabPane>
              <!-- 节拍 -->
              <NTabPane name="beats" :tab="`${t('world.beats')}（${worldResult.beats.length}）`">
                <NDataTable
                  :columns="beatColumns"
                  :data="worldResult.beats"
                  :pagination="{ pageSize: 10 }"
                  size="small"
                />
              </NTabPane>
              <!-- 风格 -->
              <NTabPane name="style_hints" :tab="`${t('world.styleHints')}（${worldResult.style_hints.length}）`">
                <NDataTable
                  :columns="styleColumns"
                  :data="worldResult.style_hints"
                  :pagination="{ pageSize: 10 }"
                  size="small"
                />
              </NTabPane>
            </NTabs>
          </template>
          <NEmpty v-else description="尚未抽离，请选择章节后点击「开始抽离」" style="margin-top:24px" />
        </NCard>
      </NTabPane>

      <!-- ═══ Tab 5: 实体对应表 (新增) ═══ -->
      <NTabPane name="entity_mapping" :tab="t('entity.mappingTitle')">
        <NCard>
          <!-- 筛选区 -->
          <NGrid :cols="4" :x-gap="8" :y-gap="8" responsive="screen" item-responsive style="margin-bottom:12px">
            <NGridItem span="0:4 900:1">
              <NFormItem label="类型">
                <NSelect
                  v-model:value="emTypeFilter"
                  :options="emTypeOptions"
                  clearable
                  placeholder="全部类型"
                />
              </NFormItem>
            </NGridItem>
            <NGridItem span="0:4 900:1">
              <NFormItem label="状态">
                <NSelect
                  v-model:value="emStatusFilter"
                  :options="emStatusOptions"
                  clearable
                  placeholder="全部状态"
                />
              </NFormItem>
            </NGridItem>
            <NGridItem span="0:4 900:2">
              <NFormItem label="关键词">
                <NInput v-model:value="emKeywordFilter" placeholder="搜索规范名/别名" clearable />
              </NFormItem>
            </NGridItem>
          </NGrid>
          <NSpace style="margin-bottom:12px">
            <NButton type="primary" @click="onLoadEntityMappings">{{ t('common.search') }}</NButton>
            <NButton :loading="isBuildingMapping" @click="onBuildEntityMapping">{{ t('entity.build') }}</NButton>
          </NSpace>

          <NDataTable
            :columns="entityMappingColumns"
            :data="entityMappings"
            :pagination="{ pageSize: 15 }"
            size="small"
          />

          <!-- Name Localization Section -->
          <NDivider style="margin-top:24px">{{ t('entity.nameLocalization') }}</NDivider>
          <NGrid :cols="4" :x-gap="8" :y-gap="8" responsive="screen" item-responsive style="margin-bottom:12px">
            <NGridItem span="0:4 900:1">
              <NFormItem label="目标语言">
                <NSelect v-model:value="nlTargetLanguage" :options="languageOptions" />
              </NFormItem>
            </NGridItem>
            <NGridItem span="0:4 900:1">
              <NFormItem label="文化背景">
                <NInput v-model:value="nlCultureProfile" placeholder="如: western_contemporary" clearable />
              </NFormItem>
            </NGridItem>
            <NGridItem span="0:4 900:2">
              <NFormItem label="模型 Provider">
                <NSelect v-model:value="nlProviderId" :options="providerOptions" filterable placeholder="选择 Provider" />
              </NFormItem>
            </NGridItem>
          </NGrid>
          <NButton
            type="primary"
            :loading="isSuggestingNames"
            :disabled="!nlProviderId"
            @click="onSuggestNames"
            style="margin-bottom:16px"
          >{{ t('entity.suggestNames') }}</NButton>

          <template v-if="nlSuggestions.length">
            <NCollapse>
              <NCollapseItem
                v-for="sug in nlSuggestions"
                :key="sug.entity_id"
                :title="`${sug.canonical_name}（${sug.entity_type || '?'}）`"
                :name="sug.entity_id"
              >
                <NSpace wrap>
                  <NCard
                    v-for="cand in sug.candidates"
                    :key="cand.name"
                    size="small"
                    style="min-width:200px;max-width:280px"
                  >
                    <NSpace vertical size="small">
                      <NText strong>{{ cand.name }}</NText>
                      <NTag size="small" :type="namePolicyTagType(cand.naming_policy)">
                        {{ namePolicyLabel(cand.naming_policy) }}
                      </NTag>
                      <NTag v-if="sug.recommended_name && sug.recommended_name === cand.name" size="small" type="success">推荐</NTag>
                      <NText depth="3" style="font-size:12px">{{ cand.rationale }}</NText>
                      <NButton
                        size="small"
                        type="primary"
                        :loading="isApplyingName === sug.entity_id"
                        @click="onApplyName(sug.entity_id, cand.name, cand.naming_policy, cand.rationale)"
                      >应用并锁定</NButton>
                    </NSpace>
                  </NCard>
                </NSpace>
              </NCollapseItem>
            </NCollapse>
          </template>

          <!-- Translate Modal -->
          <NModal v-model:show="showTranslateModal" title="补译名（本土化）" preset="dialog" style="width:480px">
            <NText style="display:block;margin-bottom:8px">
              为「{{ translateTarget?.canonical_name }}」一次性补充多语言本土化姓名
            </NText>
            <NText depth="3" style="display:block;margin-bottom:8px;font-size:12px">
              本功能会按目标语言生成完整文化等效姓名，并按语言锁定，避免出现 Wang/Li 等音译残留。
            </NText>
            <NFormItem label="目标语言">
              <NSelect
                v-model:value="translateLangs"
                :options="languageOptions"
                multiple
                placeholder="选择目标语言"
              />
            </NFormItem>
            <NFormItem label="模型 Provider">
              <NSelect v-model:value="translateProviderId" :options="providerOptions" filterable />
            </NFormItem>
            <template #action>
              <NSpace>
                <NButton type="primary" :loading="isTranslating" @click="onTranslateEntity">执行本土化补译名</NButton>
                <NButton @click="showTranslateModal = false">{{ t('common.cancel') }}</NButton>
              </NSpace>
            </template>
          </NModal>

          <!-- Merge Modal -->
          <NModal v-model:show="showMergeModal" title="合并实体" preset="dialog" style="width:480px">
            <NText style="display:block;margin-bottom:8px">
              将「{{ mergeSource?.canonical_name }}」合并至目标实体（软删当前，别名并入目标）
            </NText>
            <NFormItem label="合并目标">
              <NSelect
                v-model:value="mergeTargetId"
                :options="entityMappingOptions"
                filterable
                placeholder="选择目标实体"
              />
            </NFormItem>
            <template #action>
              <NSpace>
                <NButton type="warning" :loading="isMerging" @click="onMergeEntity">执行合并</NButton>
                <NButton @click="showMergeModal = false">{{ t('common.cancel') }}</NButton>
              </NSpace>
            </template>
          </NModal>
        </NCard>
      </NTabPane>

      <!-- ═══ Tab 6: 翻译工程 ═══ -->
      <NTabPane name="translation" tab="转译工程">

        <!-- ── 顶部筛选栏 ── -->
        <NCard style="margin-bottom:12px" :bordered="false">
          <NGrid :cols="5" :x-gap="8" :y-gap="4" responsive="screen" item-responsive>
            <NGridItem span="0:5 900:1">
              <NFormItem label="语言对" :show-feedback="false">
                <NSelect
                  v-model:value="tpLangPairFilter"
                  :options="langPairOptions"
                  clearable
                  placeholder="全部语言对"
                />
              </NFormItem>
            </NGridItem>
            <NGridItem span="0:5 900:1">
              <NFormItem label="状态" :show-feedback="false">
                <NSelect
                  v-model:value="tpStatusFilter"
                  :options="tpStatusOptions"
                  clearable
                  placeholder="全部状态"
                />
              </NFormItem>
            </NGridItem>
            <NGridItem span="0:5 900:3">
              <NSpace style="margin-top:22px">
                <NButton type="primary" @click="showCreateTranslation = true">+ 新建工程</NButton>
                <NButton @click="onLoadTranslationProjects">{{ t('common.refresh') }}</NButton>
                <NText depth="3" style="font-size:12px;line-height:34px">
                  共 {{ filteredTranslationProjects.length }} 个工程
                </NText>
              </NSpace>
            </NGridItem>
          </NGrid>
        </NCard>

        <!-- ── 中间：列表 + 右侧详情 ── -->
        <NGrid :cols="3" :x-gap="12">

          <!-- 工程列表（占 2/3） -->
          <NGridItem span="2">
            <NCard :bordered="false" style="padding:0">
              <NDataTable
                :columns="translationColumns"
                :data="filteredTranslationProjects"
                :pagination="{ pageSize: 10 }"
                :row-props="(row: TranslationProjectResponse) => ({
                  style: selectedTp?.id === row.id ? 'background:#f0f7ff;cursor:pointer' : 'cursor:pointer',
                  onClick: () => onSelectTp(row),
                })"
                size="small"
              />
            </NCard>
          </NGridItem>

          <!-- 右侧详情面板（占 1/3） -->
          <NGridItem>
            <template v-if="selectedTp">
              <NCard size="small" title="工程详情" style="position:sticky;top:12px">
                <!-- 基本参数 -->
                <NDescriptions :column="1" bordered label-placement="left" size="small" style="margin-bottom:12px">
                  <NDescriptionsItem label="语言对">
                    <NTag size="small">{{ selectedTp.source_language_code }}</NTag>
                    → <NTag size="small" type="info">{{ selectedTp.target_language_code }}</NTag>
                  </NDescriptionsItem>
                  <NDescriptionsItem label="状态">
                    <NTag :type="STATUS_TYPE_MAP[selectedTp.status] ?? 'default'" size="small">
                      {{ selectedTp.status }}
                    </NTag>
                  </NDescriptionsItem>
                  <NDescriptionsItem label="一致性">{{ selectedTp.consistency_mode }}</NDescriptionsItem>
                  <NDescriptionsItem label="Provider">{{ selectedTp.model_provider_id ?? '未配置' }}</NDescriptionsItem>
                </NDescriptions>

                <!-- 进度 -->
                <NDivider title-placement="left" style="margin:8px 0">翻译进度</NDivider>
                <NProgress
                  type="line"
                  :percentage="tpProgress(selectedTp)"
                  :indicator-placement="'inside'"
                  :status="tpProgress(selectedTp) >= 100 ? 'success' : 'default'"
                  style="margin-bottom:8px"
                />
                <NGrid :cols="3" :x-gap="4" style="margin-bottom:8px">
                  <NGridItem>
                    <NStatistic label="总块" :value="tpStat(selectedTp, 'total')" />
                  </NGridItem>
                  <NGridItem>
                    <NStatistic label="已译" :value="tpStat(selectedTp, 'translated')" />
                  </NGridItem>
                  <NGridItem>
                    <NStatistic label="已审" :value="tpStat(selectedTp, 'reviewed')" />
                  </NGridItem>
                </NGrid>

                <!-- 术语词典预览 -->
                <template v-if="selectedTpGlossaryPreview.length">
                  <NDivider title-placement="left" style="margin:8px 0">术语词典</NDivider>
                  <NDescriptions :column="1" size="small" style="margin-bottom:8px">
                    <NDescriptionsItem
                      v-for="item in selectedTpGlossaryPreview"
                      :key="item.src"
                      :label="item.src"
                    >{{ item.tgt }}</NDescriptionsItem>
                  </NDescriptions>
                  <NText v-if="selectedTpGlossaryTotal > 5" depth="3" style="font-size:11px">
                    + {{ selectedTpGlossaryTotal - 5 }} 条（工作台查看全部）
                  </NText>
                </template>
                <NText v-else depth="3" style="font-size:12px;display:block;margin-bottom:4px">
                  术语词典为空
                </NText>

                <!-- 告警预览 -->
                <NDivider title-placement="left" style="margin:8px 0">告警</NDivider>
                <NSpace align="center" style="margin-bottom:12px">
                  <NBadge
                    :value="tpStat(selectedTp, 'open_warnings')"
                    :max="99"
                    :type="tpStat(selectedTp, 'open_warnings') > 0 ? 'warning' : 'success'"
                  >
                    <NTag size="small">未解决告警</NTag>
                  </NBadge>
                  <NText depth="3" style="font-size:12px">工作台可查看详情</NText>
                </NSpace>

                <!-- 进入工作台 -->
                <NButton
                  block
                  type="primary"
                  size="large"
                  @click="openTranslationWorkbench(selectedTp.id)"
                >
                  打开工作台 →
                </NButton>
              </NCard>
            </template>
            <NEmpty v-else description="点击左侧工程行查看详情" style="margin-top:64px" />
          </NGridItem>
        </NGrid>

        <!-- 新建工程弹框 -->
        <NModal v-model:show="showCreateTranslation" :title="t('novels.newTranslation')" preset="dialog">
          <NForm label-placement="top">
            <NFormItem label="源语言">
              <NSelect v-model:value="newTpSourceLang" :options="languageOptions" />
            </NFormItem>
            <NFormItem label="目标语言">
              <NSelect v-model:value="newTpTargetLang" :options="languageOptions" />
            </NFormItem>
            <NFormItem label="翻译模型 Provider">
              <NSelect
                v-model:value="newTpProviderId"
                :options="providerOptions"
                clearable
                filterable
                placeholder="选择模型 Provider（可选）"
              />
            </NFormItem>
            <NFormItem label="一致性模式">
              <NSelect v-model:value="newTpConsistencyMode" :options="consistencyModeOptions" />
            </NFormItem>
          </NForm>
          <template #action>
            <NSpace>
              <NButton type="primary" :loading="isCreatingTp" @click="onCreateTranslationProject">{{ t('common.create') }}</NButton>
              <NButton @click="showCreateTranslation = false">{{ t('common.cancel') }}</NButton>
            </NSpace>
          </template>
        </NModal>

      </NTabPane>

    </NTabs>

    <NAlert v-if="message" type="success" :show-icon="true">{{ message }}</NAlert>
    <NAlert v-if="errorMessage" type="error" :show-icon="true">{{ errorMessage }}</NAlert>
  </div>
</template>

<script setup lang="ts">
import { computed, h, onMounted, reactive, ref, watch } from "vue";
import { useRouter } from "vue-router";
import {
  NAlert,
  NBadge,
  NButton,
  NCard,
  NCheckbox,
  NCheckboxGroup,
  NCollapse,
  NCollapseItem,
  NDataTable,
  NDescriptions,
  NDescriptionsItem,
  NDivider,
  NEmpty,
  NForm,
  NFormItem,
  NGrid,
  NGridItem,
  NInput,
  NInputNumber,
  NModal,
  NPopconfirm,
  NProgress,
  NSelect,
  NSpace,
  NStatistic,
  NTabPane,
  NTabs,
  NTag,
  NText,
  type DataTableColumns,
} from "naive-ui";
import { useI18n } from "@/composables/useI18n";

import {
  applyName,
  buildEntityMapping,
  createChapter,
  createTranslationProject,
  deleteChapter,
  deleteEntityMapping,
  detectFormat,
  generateScript,
  generateWorldModel,
  getNovelTeam,
  getScript,
  getWorldModel,
  listChapters,
  listEntityMappings,
  listPersonaPacks,
  listProviders,
  listSkillRuns,
  listTranslationProjects,
  mergeEntityMapping,
  regenerateScript,
  regenerateWorldModel,
  setNovelTeam,
  suggestNames,
  translateEntityMapping,
  type ChapterResponse,
  type EntityMappingItem,
  type FormatDetectResponse,
  type NameSuggestion,
  type NovelTeamMember,
  type PersonaPackResponse,
  type ProviderResponse,
  type ScriptResponse,
  type SuggestNameResponse,
  type TranslationProjectResponse,
  type WorldModelResponse,
} from "@/api/product";

const props = defineProps<{ novelId: string }>();
const { t } = useI18n();
const router = useRouter();

// ─── Constants ────────────────────────────────────────────────────────────────
const ALL_ROLE_TEMPLATES = [
  { id: "director",           label: "导演" },
  { id: "art_director",       label: "美术指导" },
  { id: "dop",                label: "摄影指导" },
  { id: "stunt_coordinator",  label: "武术指导" },
  { id: "script_supervisor",  label: "剧本督导" },
  { id: "translator",         label: "翻译" },
  { id: "voice_director",     label: "配音导演" },
  { id: "sound_designer",     label: "音效设计" },
  { id: "vfx_supervisor",     label: "视效监督" },
  { id: "editor",             label: "剪辑师" },
  { id: "colorist",           label: "调色师" },
  { id: "producer",           label: "制片人" },
  { id: "casting_director",   label: "选角导演" },
  { id: "prop_master",        label: "道具师" },
  { id: "costume_designer",   label: "服装设计" },
  { id: "makeup_artist",      label: "化妆师" },
  { id: "set_designer",       label: "场景设计" },
  { id: "storyboard_artist",  label: "分镜师" },
  { id: "concept_artist",     label: "概念设计师" },
  { id: "music_director",     label: "音乐总监" },
  { id: "narrator",           label: "旁白" },
  { id: "dialogue_writer",    label: "台词作家" },
  { id: "action_director",    label: "动作导演" },
  { id: "post_supervisor",    label: "后期监督" },
  { id: "qa_reviewer",        label: "质量审核" },
  { id: "localization_lead",  label: "本地化主管" },
  { id: "ai_supervisor",      label: "AI 监督" },
  { id: "technical_director", label: "技术总监" },
  { id: "executive_producer", label: "执行制片" },
  { id: "creative_director",  label: "创意总监" },
] as const;

const roleLabelMap: Record<string, string> = Object.fromEntries(
  ALL_ROLE_TEMPLATES.map(r => [r.id, r.label])
);

const languageOptions = [
  { label: "简体中文 (zh-CN)", value: "zh-CN" },
  { label: "英语 (US/Global) / English", value: "en-US" },
  { label: "日语 (ja-JP) / 日本語", value: "ja-JP" },
  { label: "阿拉伯语 (ar-SA) / العربية", value: "ar-SA" },
  { label: "西语 (es-MX) / Español", value: "es-MX" },
  { label: "越南语 (vi-VN) / Tiếng Việt", value: "vi-VN" },
  { label: "葡萄牙语 (pt-BR) / Português", value: "pt-BR" },
  { label: "印地语 (hi-IN) / हिन्दी", value: "hi-IN" },
  { label: "德语 (de-DE) / Deutsch", value: "de-DE" },
  { label: "菲律宾语 (tl-PH) / Filipino", value: "tl-PH" },
];

const consistencyModeOptions = [
  { label: "平衡 (balanced) — 仅锁定实体报警", value: "balanced" },
  { label: "严格 (strict) — 所有警告必须处理", value: "strict" },
  { label: "自由 (free) — 不校验", value: "free" },
];

const granularityOptions = [
  { label: "粗粒度 (coarse)", value: "coarse" },
  { label: "普通 (normal)", value: "normal" },
  { label: "细粒度 (fine)", value: "fine" },
];

const extractionLevelOptions = [
  { label: "基础 (basic)", value: "basic" },
  { label: "丰富 (rich)", value: "rich" },
  { label: "电影级 (cinematic)", value: "cinematic" },
];

const emTypeOptions = [
  { label: "人物 (character)", value: "character" },
  { label: "场景 (location)", value: "location" },
  { label: "道具 (prop)", value: "prop" },
  { label: "风格 (style)", value: "style" },
  { label: "事件 (event)", value: "event" },
];

const emStatusOptions = [
  { label: "未绑定 (unbound)", value: "unbound" },
  { label: "候选 (candidate)", value: "candidate" },
  { label: "已锁定 (locked)", value: "locked" },
  { label: "漂移 (drifted)", value: "drifted" },
];

const CONTINUITY_STATUS_TYPE: Record<string, "default" | "info" | "success" | "warning" | "error"> = {
  unbound: "default",
  candidate: "info",
  locked: "success",
  drifted: "warning",
};

const NAME_POLICY_LABEL: Record<string, string> = {
  transliteration: "音译",
  literal: "字面",
  cultural_equivalent: "文化等价",
  hybrid: "混合",
  character_driven: "性格驱动",
  setting_authentic: "设定贴合",
};

function namePolicyLabel(policy: string | null | undefined): string {
  return NAME_POLICY_LABEL[policy ?? ""] ?? (policy || "未设置");
}

function namePolicyTagType(
  policy: string | null | undefined,
): "default" | "success" | "warning" | "info" {
  if (policy === "cultural_equivalent") return "success";
  if (policy === "hybrid" || policy === "setting_authentic") return "warning";
  if (policy === "literal") return "info";
  return "default";
}

// ─── State ────────────────────────────────────────────────────────────────────
const tenantId = ref("default");
const projectId = ref("default");
const activeTab = ref("chapters");

// Chapters
const chapters = ref<ChapterResponse[]>([]);
const showAddChapter = ref(false);
const newChapterNo = ref(1);
const newChapterLanguage = ref("zh-CN");
const newChapterTitle = ref("");
const newChapterContent = ref("");

// Team
const personaPacks = ref<PersonaPackResponse[]>([]);
const isSavingTeam = ref(false);
const teamSaveResult = ref("");
const selectedRoleKeys = ref<string[]>(["director", "translator", "voice_director"]);
const teamBindings = reactive<Record<string, string | null>>({});

// Script conversion
const scriptChapterId = ref<string | null>(null);
const scriptGranularity = ref("normal");
const scriptProviderId = ref<string | null>(null);
const isDetectingFormat = ref(false);
const isConvertingScript = ref(false);
const isNormalizingScript = ref(false);
const isLoadingScript = ref(false);
const formatDetectResult = ref<FormatDetectResponse | null>(null);
const scriptResult = ref<ScriptResponse | null>(null);

// World model
const worldChapterId = ref<string | null>(null);
const worldLevel = ref("rich");
const worldProviderId = ref<string | null>(null);
const isExtractingWorld = ref(false);
const isRegeneratingWorld = ref(false);
const isLoadingWorld = ref(false);
const worldResult = ref<WorldModelResponse | null>(null);
const worldLatestRunStatus = ref<string | null>(null);

// Name localization
const nlSuggestions = ref<NameSuggestion[]>([]);
const nlTargetLanguage = ref("en-US");
const nlCultureProfile = ref("");
const nlProviderId = ref<string | null>(null);
const isSuggestingNames = ref(false);
const isApplyingName = ref<string | null>(null);  // entity_id being applied

// Entity mapping
const entityMappings = ref<EntityMappingItem[]>([]);
const emTypeFilter = ref<string | null>(null);
const emStatusFilter = ref<string | null>(null);
const emKeywordFilter = ref("");
const isBuildingMapping = ref(false);
// Translate modal
const showTranslateModal = ref(false);
const translateTarget = ref<EntityMappingItem | null>(null);
const translateLangs = ref<string[]>(["en-US", "ja-JP"]);
const translateProviderId = ref<string | null>(null);
const isTranslating = ref(false);
// Merge modal
const showMergeModal = ref(false);
const mergeSource = ref<EntityMappingItem | null>(null);
const mergeTargetId = ref<string | null>(null);
const isMerging = ref(false);

// Translation Projects
const providers = ref<ProviderResponse[]>([]);
const translationProjects = ref<TranslationProjectResponse[]>([]);
const showCreateTranslation = ref(false);
const isCreatingTp = ref(false);
const newTpSourceLang = ref("zh-CN");
const newTpTargetLang = ref("en-US");
const newTpProviderId = ref<string | null>(null);
const newTpConsistencyMode = ref("balanced");
// Translation filter + detail panel
const tpStatusFilter = ref<string | null>(null);
const tpLangPairFilter = ref<string | null>(null);
const selectedTp = ref<TranslationProjectResponse | null>(null);

const message = ref("");
const errorMessage = ref("");

// ─── Computed ─────────────────────────────────────────────────────────────────
const personaOptions = computed(() =>
  personaPacks.value.map(p => ({ label: p.name, value: p.id }))
);

const providerOptions = computed(() =>
  providers.value.map(p => ({ label: p.name, value: p.id }))
);

const chapterOptions = computed(() =>
  chapters.value.map(c => ({
    label: `Ch.${c.chapter_no} ${c.title ?? ""}`.trim(),
    value: c.id,
  }))
);

const entityMappingOptions = computed(() =>
  entityMappings.value.map(e => ({
    label: `[${e.entity_type ?? "?"}] ${e.canonical_name}`,
    value: e.id,
  }))
);
const worldRunBusy = computed(() => worldLatestRunStatus.value === "running" || worldLatestRunStatus.value === "queued");
const worldCanGenerate = computed(() =>
  Boolean(worldChapterId.value && worldProviderId.value && !isExtractingWorld.value && !worldRunBusy.value)
);
const worldCanRegenerate = computed(() =>
  Boolean(worldChapterId.value && worldProviderId.value && !isRegeneratingWorld.value && !worldRunBusy.value)
);

// ─── World model table columns ─────────────────────────────────────────────────
const evidenceRender = (row: Record<string, unknown>) =>
  h("div", { style: "max-width:300px;font-size:11px;color:#888" },
    ((row.evidence as string[]) || []).slice(0, 2).join("；")
  );

const characterColumns: DataTableColumns = [
  { title: "名称", key: "name", width: 100 },
  { title: "外貌", key: "appearance", ellipsis: true },
  { title: "声音", key: "voice_hints", width: 120 },
  { title: "原文证据", key: "evidence", render: evidenceRender },
];

const locationColumns: DataTableColumns = [
  { title: "名称", key: "name", width: 100 },
  { title: "类型", key: "type", width: 80 },
  { title: "视觉词", key: "visual_keywords", render: (row) => h("span", ((row.visual_keywords as string[]) || []).join("、")) },
  { title: "原文证据", key: "evidence", render: evidenceRender },
];

const propColumns: DataTableColumns = [
  { title: "名称", key: "name", width: 100 },
  { title: "类型", key: "type", width: 80 },
  { title: "持有者", key: "owner", width: 80 },
  { title: "用途", key: "usage", ellipsis: true },
  { title: "原文证据", key: "evidence", render: evidenceRender },
];

const beatColumns: DataTableColumns = [
  { title: "节拍", key: "title", ellipsis: true },
  { title: "张力", key: "tension_level", width: 60 },
  { title: "地点", key: "location", width: 80 },
  { title: "原文证据", key: "evidence", render: evidenceRender },
];

const styleColumns: DataTableColumns = [
  { title: "光影", key: "lighting_style", ellipsis: true },
  { title: "镜头", key: "camera_language", ellipsis: true },
  { title: "节奏", key: "pacing", width: 80 },
  { title: "类型标签", key: "genre_tags", render: (row) => h("span", ((row.genre_tags as string[]) || []).join("、")) },
  { title: "原文证据", key: "evidence", render: evidenceRender },
];

// ─── Entity mapping columns ────────────────────────────────────────────────────
const entityMappingColumns: DataTableColumns<EntityMappingItem> = [
  { title: "类型", key: "entity_type", width: 80 },
  { title: t('entity.canonicalName'), key: "canonical_name" },
  {
    title: "多语言译名",
    key: "translations_json",
    render: (row) => {
      const t = row.translations_json ?? {};
      return h("span", { style: "font-size:11px" },
        Object.entries(t).map(([k, v]) => `${k}:${v}`).join("  ")
      );
    },
  },
  {
    title: "别名",
    key: "aliases_json",
    render: (row) => h("span", { style: "font-size:11px" }, (row.aliases_json ?? []).join("、")),
  },
  {
    title: t('entity.status'),
    key: "continuity_status",
    width: 100,
    render: (row) =>
      h(NTag, {
        type: CONTINUITY_STATUS_TYPE[row.continuity_status] ?? "default",
        size: "small",
      }, { default: () => row.continuity_status }),
  },
  {
    title: "命名策略",
    key: "naming_policy",
    width: 120,
    render: (row) =>
      h(NTag, { size: "small", type: namePolicyTagType(row.naming_policy) }, {
        default: () => namePolicyLabel(row.naming_policy),
      }),
  },
  {
    title: "锁定",
    key: "locked",
    width: 70,
    render: (row) => h(NTag, { size: "small", type: row.locked ? "success" : "default" }, {
      default: () => (row.locked ? "是" : "否"),
    }),
  },
  {
    title: "漂移分",
    key: "drift_score",
    width: 80,
    render: (row) => {
      const score = Number(row.drift_score || 0);
      return h(
        NText,
        { type: score > 0.8 ? "error" : "default" },
        { default: () => score.toFixed(2) },
      );
    },
  },
  { title: "命名理由", key: "rationale", ellipsis: true },
  {
    title: "操作",
    key: "action",
    width: 240,
    render: (row) =>
      h(NSpace, { size: 4 }, {
        default: () => [
          h(NButton, {
            size: "tiny",
            type: "info",
            onClick: () => openTranslateModal(row),
          }, { default: () => "补译名（本土化）" }),
          h(NButton, {
            size: "tiny",
            type: "primary",
            onClick: () => void onSuggestNamesForEntity(row.id),
          }, { default: () => "本土化命名" }),
          h(NButton, {
            size: "tiny",
            onClick: () => openMergeModal(row),
          }, { default: () => t('entity.merge') }),
          h(NPopconfirm, {
            onPositiveClick: () => void onDeleteEntityMapping(row.id),
          }, {
            trigger: () => h(NButton, { size: "tiny", type: "error" }, { default: () => t('common.delete') }),
            default: () => "确认删除该实体映射？",
          }),
        ],
      }),
  },
];

// ─── Chapter columns ───────────────────────────────────────────────────────────
const chapterColumns: DataTableColumns<ChapterResponse> = [
  { title: "章节号", key: "chapter_no", width: 80 },
  { title: "标题", key: "title" },
  { title: "语言", key: "language_code", width: 100 },
  {
    title: "操作",
    key: "action",
    width: 250,
    render: (row) =>
      h(NSpace, { size: 6 }, {
        default: () => [
          h(NButton, {
            size: "tiny",
            type: "primary",
            onClick: () => openChapterEditor(row),
          }, { default: () => "编辑" }),
          h(NButton, {
            size: "tiny",
            type: "info",
            onClick: () => openChapterPreview(row),
          }, { default: () => "预览" }),
          h(NButton, {
            size: "tiny",
            onClick: () => openChapterRevisions(row),
          }, { default: () => "历史" }),
          h(NPopconfirm, {
            onPositiveClick: () => void onDeleteChapter(row.id),
          }, {
            trigger: () => h(NButton, { size: "tiny", type: "error" }, { default: () => "删除" }),
            default: () => "确认删除该章节？",
          }),
        ],
      }),
  },
];

// ─── Translation columns ───────────────────────────────────────────────────────
const STATUS_TYPE_MAP: Record<string, "default" | "info" | "success" | "warning" | "error"> = {
  draft: "default",
  in_progress: "info",
  completed: "success",
  archived: "warning",
};

// ─── Translation: helpers + computed ──────────────────────────────────────────

function tpStat(tp: TranslationProjectResponse, key: string): number {
  return Number((tp.stats_json as Record<string, number> | null)?.[key] ?? 0);
}

function tpProgress(tp: TranslationProjectResponse): number {
  const total = tpStat(tp, "total");
  if (total === 0) return 0;
  return Math.round((tpStat(tp, "translated") / total) * 100);
}

function onSelectTp(row: TranslationProjectResponse): void {
  selectedTp.value = row;
}

const filteredTranslationProjects = computed(() =>
  translationProjects.value.filter(tp => {
    if (tpStatusFilter.value && tp.status !== tpStatusFilter.value) return false;
    if (tpLangPairFilter.value) {
      const pair = `${tp.source_language_code}→${tp.target_language_code}`;
      if (pair !== tpLangPairFilter.value) return false;
    }
    return true;
  })
);

const langPairOptions = computed(() => {
  const pairs = new Set(translationProjects.value.map(
    tp => `${tp.source_language_code}→${tp.target_language_code}`
  ));
  return Array.from(pairs).map(p => ({ label: p, value: p }));
});

const tpStatusOptions = [
  { label: "草稿", value: "draft" },
  { label: "进行中", value: "in_progress" },
  { label: "已完成", value: "completed" },
  { label: "已归档", value: "archived" },
];

const selectedTpGlossaryPreview = computed(() => {
  if (!selectedTp.value) return [];
  return Object.entries(selectedTp.value.term_dictionary_json ?? {})
    .slice(0, 5)
    .map(([src, tgt]) => ({ src, tgt: String(tgt) }));
});

const selectedTpGlossaryTotal = computed(() =>
  Object.keys(selectedTp.value?.term_dictionary_json ?? {}).length
);

const translationColumns: DataTableColumns<TranslationProjectResponse> = [
  {
    title: "语言对",
    key: "lang_pair",
    width: 140,
    render: (row) =>
      h("span", { style: "font-size:12px" },
        `${row.source_language_code} → ${row.target_language_code}`
      ),
  },
  {
    title: "状态",
    key: "status",
    width: 90,
    render: (row) =>
      h(NTag, { type: STATUS_TYPE_MAP[row.status] ?? "default", size: "small" }, {
        default: () => row.status,
      }),
  },
  {
    title: "进度",
    key: "progress",
    width: 100,
    render: (row) => {
      const pct = tpProgress(row);
      return h(NProgress, {
        type: "line",
        percentage: pct,
        indicatorPlacement: "inside",
        style: "min-width:80px",
        status: pct >= 100 ? "success" : "default",
      });
    },
  },
  {
    title: "块数",
    key: "blocks",
    width: 60,
    render: (row) => h("span", tpStat(row, "total")),
  },
  {
    title: "已译/已审",
    key: "translated",
    width: 90,
    render: (row) =>
      h("span", { style: "font-size:12px" },
        `${tpStat(row, "translated")} / ${tpStat(row, "reviewed")}`
      ),
  },
  {
    title: "告警",
    key: "warnings",
    width: 60,
    render: (row) => {
      const n = tpStat(row, "open_warnings");
      return h(NTag, {
        type: n > 0 ? "warning" : "success",
        size: "small",
        round: true,
      }, { default: () => String(n) });
    },
  },
  {
    title: "创建",
    key: "created_at",
    render: (row) => h("span", { style: "font-size:11px" }, row.created_at.slice(0, 10)),
  },
];

// ─── Helpers ───────────────────────────────────────────────────────────────────
function stringifyError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function clearNotice(): void {
  message.value = "";
  errorMessage.value = "";
}

function goBack(): void {
  void router.push({ name: "studio-novels" });
}

function openChapterEditor(chapter: ChapterResponse): void {
  void router.push({ name: "studio-chapter-editor", params: { novelId: props.novelId, chapterId: chapter.id } });
}

function openChapterPreview(chapter: ChapterResponse): void {
  void router.push({ name: "studio-chapter-preview", params: { novelId: props.novelId, chapterId: chapter.id } });
}

function openChapterRevisions(chapter: ChapterResponse): void {
  void router.push({ name: "studio-chapter-revisions", params: { novelId: props.novelId, chapterId: chapter.id } });
}

function openTranslationWorkbench(tpId: string): void {
  void router.push({ name: "studio-translation-project", params: { projectId: tpId } });
}

function openTranslateModal(entity: EntityMappingItem): void {
  translateTarget.value = entity;
  translateProviderId.value = providers.value[0]?.id ?? null;
  showTranslateModal.value = true;
}

function openMergeModal(entity: EntityMappingItem): void {
  mergeSource.value = entity;
  mergeTargetId.value = null;
  showMergeModal.value = true;
}

function onSelectAllRoles(): void {
  selectedRoleKeys.value = ALL_ROLE_TEMPLATES.map(r => r.id);
}

function onClearAllRoles(): void {
  selectedRoleKeys.value = [];
}

// ─── API Calls ─────────────────────────────────────────────────────────────────
async function onReloadAll(): Promise<void> {
  clearNotice();
  try {
    const [chapterList, packs, providerList] = await Promise.all([
      listChapters(props.novelId),
      listPersonaPacks({ tenant_id: tenantId.value, project_id: projectId.value }),
      listProviders(tenantId.value, projectId.value),
    ]);
    chapters.value = chapterList;
    personaPacks.value = packs;
    providers.value = providerList;
    if (!scriptProviderId.value && providerList.length > 0) scriptProviderId.value = providerList[0].id;
    if (!worldProviderId.value && providerList.length > 0) worldProviderId.value = providerList[0].id;
    if (!nlProviderId.value && providerList.length > 0) nlProviderId.value = providerList[0].id;
    if (!translateProviderId.value && providerList.length > 0) translateProviderId.value = providerList[0].id;
    if (!newTpProviderId.value && providerList.length > 0) newTpProviderId.value = providerList[0].id;
    await Promise.all([onLoadTeam(), onLoadTranslationProjects()]);
  } catch (error) {
    errorMessage.value = `reload failed: ${stringifyError(error)}`;
  }
}

async function onLoadTeam(): Promise<void> {
  try {
    const resp = await getNovelTeam(props.novelId, { tenant_id: tenantId.value, project_id: projectId.value });
    const savedKeys = Object.keys(resp.team || {});
    if (savedKeys.length > 0) {
      selectedRoleKeys.value = savedKeys;
      for (const key of savedKeys) {
        teamBindings[key] = resp.team[key]?.persona_pack_id ?? null;
      }
    }
  } catch {
    // team not set yet
  }
}

async function onCreateChapter(): Promise<void> {
  clearNotice();
  try {
    await createChapter(props.novelId, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
      chapter_no: newChapterNo.value,
      language_code: newChapterLanguage.value,
      title: newChapterTitle.value || undefined,
      markdown_text: newChapterContent.value,
    });
    chapters.value = await listChapters(props.novelId);
    showAddChapter.value = false;
    newChapterContent.value = "";
    newChapterTitle.value = "";
    message.value = `章节 ${newChapterNo.value} 已创建`;
  } catch (error) {
    errorMessage.value = `create chapter failed: ${stringifyError(error)}`;
  }
}

async function onDeleteChapter(chapterId: string): Promise<void> {
  clearNotice();
  try {
    await deleteChapter(chapterId, { tenant_id: tenantId.value, project_id: projectId.value });
    chapters.value = await listChapters(props.novelId);
    message.value = "章节已删除";
  } catch (error) {
    errorMessage.value = `delete chapter failed: ${stringifyError(error)}`;
  }
}

async function onSaveTeam(): Promise<void> {
  clearNotice();
  isSavingTeam.value = true;
  try {
    const team: Record<string, NovelTeamMember> = {};
    for (const roleKey of selectedRoleKeys.value) {
      const packId = teamBindings[roleKey] ?? null;
      if (packId) {
        const pack = personaPacks.value.find(p => p.id === packId);
        team[roleKey] = { persona_pack_id: packId, persona_pack_name: pack?.name ?? "" };
      } else {
        team[roleKey] = { persona_pack_id: "", persona_pack_name: roleLabelMap[roleKey] ?? roleKey };
      }
    }
    const result = await setNovelTeam(props.novelId, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
      team,
    });
    teamSaveResult.value = JSON.stringify(result, null, 2);
    message.value = `团队绑定已保存 (${selectedRoleKeys.value.length} 个职位)`;
  } catch (error) {
    errorMessage.value = `save team failed: ${stringifyError(error)}`;
  } finally {
    isSavingTeam.value = false;
  }
}

// Script workflow
async function onDetectFormat(): Promise<void> {
  if (!scriptChapterId.value) return;
  clearNotice();
  isDetectingFormat.value = true;
  try {
    formatDetectResult.value = await detectFormat(scriptChapterId.value, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
      model_provider_id: scriptProviderId.value ?? undefined,
    });
  } catch (error) {
    errorMessage.value = `format detect failed: ${stringifyError(error)}`;
  } finally {
    isDetectingFormat.value = false;
  }
}

async function onLoadScript(): Promise<void> {
  if (!scriptChapterId.value) return;
  clearNotice();
  isLoadingScript.value = true;
  try {
    scriptResult.value = await getScript(scriptChapterId.value);
    if (scriptResult.value.scenes.length) {
      message.value = `已加载缓存剧本 v${scriptResult.value.version}，共 ${scriptResult.value.scenes.length} 个场景`;
    } else {
      message.value = "暂无剧本数据，请点击「生成」";
    }
  } catch (error) {
    errorMessage.value = `load script failed: ${stringifyError(error)}`;
  } finally {
    isLoadingScript.value = false;
  }
}

async function onGenerateScript(): Promise<void> {
  if (!scriptChapterId.value || !scriptProviderId.value) return;
  clearNotice();
  isConvertingScript.value = true;
  try {
    scriptResult.value = await generateScript(scriptChapterId.value, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
      model_provider_id: scriptProviderId.value,
      granularity: scriptGranularity.value,
    });
    const label = scriptResult.value.cached ? "（命中缓存）" : "";
    message.value = `剧本生成完成${label}，v${scriptResult.value.version}，共 ${scriptResult.value.scenes.length} 个场景`;
  } catch (error) {
    errorMessage.value = `script generate failed: ${stringifyError(error)}`;
  } finally {
    isConvertingScript.value = false;
  }
}

async function onRegenerateScript(): Promise<void> {
  if (!scriptChapterId.value || !scriptProviderId.value) return;
  clearNotice();
  isNormalizingScript.value = true;
  try {
    scriptResult.value = await regenerateScript(scriptChapterId.value, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
      model_provider_id: scriptProviderId.value,
      granularity: scriptGranularity.value,
    });
    message.value = `剧本重新生成完成，v${scriptResult.value.version}，共 ${scriptResult.value.scenes.length} 个场景`;
  } catch (error) {
    errorMessage.value = `script regenerate failed: ${stringifyError(error)}`;
  } finally {
    isNormalizingScript.value = false;
  }
}

// World model
async function onLoadWorldModel(): Promise<void> {
  if (!worldChapterId.value) return;
  clearNotice();
  isLoadingWorld.value = true;
  try {
    await refreshWorldRunStatus(worldChapterId.value);
    worldResult.value = await getWorldModel(worldChapterId.value);
    const total = (worldResult.value.characters.length + worldResult.value.locations.length +
      worldResult.value.props.length + worldResult.value.beats.length + worldResult.value.style_hints.length);
    message.value = total > 0 ? `已加载缓存世界模型 v${worldResult.value.version}，共 ${total} 条` : "暂无世界模型数据，请点击「抽离」";
  } catch (error) {
    errorMessage.value = `load world model failed: ${stringifyError(error)}`;
  } finally {
    isLoadingWorld.value = false;
  }
}

async function onGenerateWorldModel(): Promise<void> {
  if (!worldChapterId.value || !worldProviderId.value) return;
  clearNotice();
  isExtractingWorld.value = true;
  worldLatestRunStatus.value = "running";
  try {
    worldResult.value = await generateWorldModel(worldChapterId.value, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
      model_provider_id: worldProviderId.value,
      level: worldLevel.value,
    });
    const total = (worldResult.value.characters.length + worldResult.value.locations.length +
      worldResult.value.props.length + worldResult.value.beats.length + worldResult.value.style_hints.length);
    const label = worldResult.value.cached ? "（命中缓存）" : "";
    message.value = `世界模型抽离完成${label}，v${worldResult.value.version}，共 ${total} 条`;
  } catch (error) {
    errorMessage.value = `world model generate failed: ${stringifyError(error)}`;
  } finally {
    await refreshWorldRunStatus(worldChapterId.value);
    isExtractingWorld.value = false;
  }
}

async function onRegenerateWorldModel(): Promise<void> {
  if (!worldChapterId.value || !worldProviderId.value) return;
  clearNotice();
  isRegeneratingWorld.value = true;
  worldLatestRunStatus.value = "running";
  try {
    worldResult.value = await regenerateWorldModel(worldChapterId.value, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
      model_provider_id: worldProviderId.value,
      level: worldLevel.value,
    });
    const total = (worldResult.value.characters.length + worldResult.value.locations.length +
      worldResult.value.props.length + worldResult.value.beats.length + worldResult.value.style_hints.length);
    message.value = `世界模型重新抽离完成，v${worldResult.value.version}，共 ${total} 条`;
  } catch (error) {
    errorMessage.value = `world model regenerate failed: ${stringifyError(error)}`;
  } finally {
    await refreshWorldRunStatus(worldChapterId.value);
    isRegeneratingWorld.value = false;
  }
}

async function refreshWorldRunStatus(chapterId: string | null): Promise<void> {
  if (!chapterId) {
    worldLatestRunStatus.value = null;
    return;
  }
  try {
    const runs = await listSkillRuns({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      skill_id: "world_model_extract",
      chapter_id: chapterId,
      limit: 1,
    });
    worldLatestRunStatus.value = runs[0]?.status ?? null;
  } catch {
    worldLatestRunStatus.value = null;
  }
}

// Entity mapping
async function onBuildEntityMapping(): Promise<void> {
  clearNotice();
  isBuildingMapping.value = true;
  try {
    const result = await buildEntityMapping(props.novelId, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
    });
    message.value = `实体对应表已更新：新增 ${result.created} 条，更新 ${result.updated} 条，共 ${result.total} 条`;
    await onLoadEntityMappings();
    activeTab.value = "entity_mapping";
  } catch (error) {
    errorMessage.value = `build entity mapping failed: ${stringifyError(error)}`;
  } finally {
    isBuildingMapping.value = false;
  }
}

async function onLoadEntityMappings(): Promise<void> {
  clearNotice();
  try {
    entityMappings.value = await listEntityMappings(props.novelId, {
      keyword: emKeywordFilter.value || undefined,
      entity_type: emTypeFilter.value || undefined,
      status: emStatusFilter.value || undefined,
    });
  } catch (error) {
    errorMessage.value = `load entity mappings failed: ${stringifyError(error)}`;
  }
}

async function onDeleteEntityMapping(entityUid: string): Promise<void> {
  clearNotice();
  try {
    await deleteEntityMapping(entityUid);
    await onLoadEntityMappings();
    message.value = "实体映射已删除";
  } catch (error) {
    errorMessage.value = `delete entity mapping failed: ${stringifyError(error)}`;
  }
}

async function onTranslateEntity(): Promise<void> {
  if (!translateTarget.value || !translateProviderId.value) return;
  clearNotice();
  isTranslating.value = true;
  try {
    const updated = await translateEntityMapping(translateTarget.value.id, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
      model_provider_id: translateProviderId.value,
      target_languages: translateLangs.value,
    });
    const idx = entityMappings.value.findIndex(e => e.id === updated.id);
    if (idx >= 0) entityMappings.value[idx] = updated;
    showTranslateModal.value = false;
    message.value = `翻译完成：${translateTarget.value.canonical_name}`;
  } catch (error) {
    errorMessage.value = `translate failed: ${stringifyError(error)}`;
  } finally {
    isTranslating.value = false;
  }
}

async function onMergeEntity(): Promise<void> {
  if (!mergeSource.value || !mergeTargetId.value) return;
  clearNotice();
  isMerging.value = true;
  try {
    await mergeEntityMapping(mergeSource.value.id, mergeTargetId.value);
    showMergeModal.value = false;
    await onLoadEntityMappings();
    message.value = `合并完成：${mergeSource.value.canonical_name} → ${mergeTargetId.value}`;
  } catch (error) {
    errorMessage.value = `merge failed: ${stringifyError(error)}`;
  } finally {
    isMerging.value = false;
  }
}

// Name localization
async function onSuggestNames(): Promise<void> {
  if (!nlProviderId.value) return;
  clearNotice();
  isSuggestingNames.value = true;
  try {
    const result = await suggestNames(props.novelId, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
      model_provider_id: nlProviderId.value,
      target_language: nlTargetLanguage.value,
      culture_profile: nlCultureProfile.value || undefined,
    });
    nlSuggestions.value = result.suggestions;
    message.value = `已生成 ${result.total} 条命名建议`;
  } catch (error) {
    errorMessage.value = `suggest names failed: ${stringifyError(error)}`;
  } finally {
    isSuggestingNames.value = false;
  }
}

async function onSuggestNamesForEntity(entityId: string): Promise<void> {
  if (!nlProviderId.value) return;
  clearNotice();
  isSuggestingNames.value = true;
  try {
    const result = await suggestNames(props.novelId, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
      model_provider_id: nlProviderId.value,
      entity_uids: [entityId],
      target_language: nlTargetLanguage.value,
      culture_profile: nlCultureProfile.value || undefined,
    });
    nlSuggestions.value = result.suggestions;
    message.value = `已生成 ${result.total} 条命名建议`;
  } catch (error) {
    errorMessage.value = `suggest names failed: ${stringifyError(error)}`;
  } finally {
    isSuggestingNames.value = false;
  }
}

async function onApplyName(
  entityId: string,
  chosenName: string,
  namingPolicy: string,
  rationale: string,
): Promise<void> {
  clearNotice();
  isApplyingName.value = entityId;
  try {
    await applyName(props.novelId, {
      entity_uid: entityId,
      chosen_name: chosenName,
      target_language: nlTargetLanguage.value,
      naming_policy: namingPolicy,
      rationale,
      lock: true,
    });
    // Remove from suggestions list after applying
    nlSuggestions.value = nlSuggestions.value.filter(s => s.entity_id !== entityId);
    message.value = `已应用「${chosenName}」并锁定`;
    await onLoadEntityMappings();
  } catch (error) {
    errorMessage.value = `apply name failed: ${stringifyError(error)}`;
  } finally {
    isApplyingName.value = null;
  }
}

async function onLoadTranslationProjects(): Promise<void> {
  try {
    translationProjects.value = await listTranslationProjects({
      novel_id: props.novelId,
      tenant_id: tenantId.value,
      project_id: projectId.value,
    });
    // Sync detail panel if previously selected project is still present
    if (selectedTp.value) {
      const refreshed = translationProjects.value.find(tp => tp.id === selectedTp.value!.id);
      selectedTp.value = refreshed ?? null;
    }
  } catch (error) {
    errorMessage.value = `load translation projects failed: ${stringifyError(error)}`;
  }
}

async function onCreateTranslationProject(): Promise<void> {
  clearNotice();
  isCreatingTp.value = true;
  try {
    const tp = await createTranslationProject({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      novel_id: props.novelId,
      source_language_code: newTpSourceLang.value,
      target_language_code: newTpTargetLang.value,
      model_provider_id: newTpProviderId.value,
      consistency_mode: newTpConsistencyMode.value,
    });
    showCreateTranslation.value = false;
    translationProjects.value = await listTranslationProjects({
      novel_id: props.novelId,
      tenant_id: tenantId.value,
      project_id: projectId.value,
    });
    message.value = `转译工程已创建，正在跳转工作台...`;
    void router.push({ name: "studio-translation-project", params: { projectId: tp.id } });
  } catch (error) {
    errorMessage.value = `create translation project failed: ${stringifyError(error)}`;
  } finally {
    isCreatingTp.value = false;
  }
}

onMounted(() => {
  void onReloadAll();
});

watch(worldChapterId, (chapterId) => {
  void refreshWorldRunStatus(chapterId);
});
</script>
