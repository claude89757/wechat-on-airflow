-- 创建行业表
CREATE TABLE public.industry (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  name TEXT NOT NULL,
  material_list UUID[] DEFAULT '{}',
  app_id TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- 创建索引以提高查询性能
CREATE INDEX idx_industry_name ON public.industry(name);

-- 启用行级安全策略
ALTER TABLE public.industry ENABLE ROW LEVEL SECURITY;

-- 允许所有用户查看行业数据
CREATE POLICY "允许所有用户查看行业信息" 
  ON public.industry FOR SELECT 
  USING (true);

-- 只有管理员可以修改行业数据（您可能需要自定义此策略）
CREATE POLICY "只有管理员可以插入行业信息" 
  ON public.industry FOR INSERT 
  WITH CHECK (auth.uid() IN (SELECT user_id FROM public.user_profiles WHERE is_active = true));
  
CREATE POLICY "只有管理员可以更新行业信息" 
  ON public.industry FOR UPDATE 
  USING (auth.uid() IN (SELECT user_id FROM public.user_profiles WHERE is_active = true));

CREATE POLICY "只有管理员可以删除行业信息" 
  ON public.industry FOR DELETE 
  USING (auth.uid() IN (SELECT user_id FROM public.user_profiles WHERE is_active = true));

-- 创建触发器自动更新updated_at字段
CREATE TRIGGER update_industry_updated_at
BEFORE UPDATE ON public.industry
FOR EACH ROW
EXECUTE FUNCTION update_modified_column();

-- 添加表和字段的注释说明
COMMENT ON TABLE public.industry IS '行业信息表，关联行业、素材列表和机器人应用ID';
COMMENT ON COLUMN public.industry.name IS '行业名称';
COMMENT ON COLUMN public.industry.material_list IS '该行业可访问的素材ID列表';
COMMENT ON COLUMN public.industry.app_id IS '该行业使用的机器人应用ID';